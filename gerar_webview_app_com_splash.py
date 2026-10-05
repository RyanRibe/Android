#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import html
import json
import platform
import re
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageOps, ImageSequence


DEFAULT_AGP_VERSION = "9.1.0"
DEFAULT_GRADLE_VERSION = "9.3.1"
DEFAULT_COMPILE_SDK = 36
DEFAULT_MIN_SDK = 23
DEFAULT_TARGET_SDK = 36
DEFAULT_FIREBASE_BOM_VERSION = "34.7.0"
DEFAULT_GOOGLE_SERVICES_VERSION = "4.4.4"


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")


def run(cmd, cwd: Path):
    print(f"\n> {' '.join(map(str, cmd))}")
    subprocess.run(cmd, cwd=str(cwd), check=True)


def validate_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SystemExit("A URL precisa começar com http:// ou https://")
    if not parsed.netloc:
        raise SystemExit("URL inválida. Exemplo: https://seudominio.com.br")
    return parsed


def validate_package(package: str):
    if not re.fullmatch(r"[a-zA-Z][\w]*(\.[a-zA-Z][\w]*)+", package):
        raise SystemExit("Package inválido. Use algo como: br.com.suaempresa.agendamento")


def safe_project_name(name: str):
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())
    return value or "WebViewApp"


def package_to_path(package: str):
    return Path(*package.split("."))


def validate_firebase_json(firebase_json: str | None, package: str) -> Path | None:
    if not firebase_json:
        return None

    firebase_config_path = Path(firebase_json).expanduser().resolve()
    if not firebase_config_path.exists():
        raise SystemExit(f"google-services.json não encontrado: {firebase_config_path}")

    if firebase_config_path.name != "google-services.json":
        print("Aviso: o arquivo Firebase deve se chamar google-services.json. Ele será copiado com esse nome.")

    try:
        firebase_config = json.loads(firebase_config_path.read_text(encoding="utf-8"))
        package_names = []
        for client in firebase_config.get("client", []):
            android_info = client.get("client_info", {}).get("android_client_info", {})
            package_name = android_info.get("package_name")
            if package_name:
                package_names.append(package_name)

        if package_names and package not in package_names:
            print(
                "Aviso: o package informado não aparece no google-services.json. "
                f"Package usado: {package}. Packages no Firebase: {', '.join(package_names)}"
            )
    except Exception as exc:
        print(f"Aviso: não foi possível validar o google-services.json: {exc}")

    return firebase_config_path



def prepare_android_splash(project_dir: Path, splash_gif: str) -> tuple[int, int, int]:
    """
    Prepara o GIF da splash para Android.

    O arquivo original pode ter uma tela 1920x1080 com muito espaço transparente
    ao redor. Esta função calcula a união da área visível de todos os frames,
    recorta apenas o conteúdo animado e cria:

    - res/drawable-nodpi/splash_logo.gif: animação usada dentro do aplicativo;
    - res/drawable-nodpi/splash_system_logo.png: primeiro frame usado pelo splash
      obrigatório do Android 12+ antes da Activity ficar pronta.
    """
    src = Path(splash_gif).expanduser().resolve()

    if not src.exists():
        raise SystemExit(f"GIF da splash não encontrado: {src}")

    try:
        image = Image.open(src)
    except Exception as exc:
        raise SystemExit(f"Não foi possível abrir o GIF da splash: {exc}") from exc

    if (image.format or "").upper() != "GIF":
        raise SystemExit(f"O arquivo da splash precisa ser GIF: {src}")

    frame_count = getattr(image, "n_frames", 1)
    frames: list[Image.Image] = []
    durations: list[int] = []
    visible_boxes = []

    for frame_index in range(frame_count):
        image.seek(frame_index)
        rgba = image.convert("RGBA")
        alpha_box = rgba.getchannel("A").getbbox()

        if alpha_box:
            visible_boxes.append(alpha_box)

        frames.append(rgba)
        durations.append(int(image.info.get("duration", 50) or 50))

    if not visible_boxes:
        crop_box = (0, 0, image.width, image.height)
    else:
        left = min(box[0] for box in visible_boxes)
        top = min(box[1] for box in visible_boxes)
        right = max(box[2] for box in visible_boxes)
        bottom = max(box[3] for box in visible_boxes)

        # Pequena margem para a animação não tocar nas bordas.
        padding = max(12, round(min(image.width, image.height) * 0.02))

        crop_box = (
            max(0, left - padding),
            max(0, top - padding),
            min(image.width, right + padding),
            min(image.height, bottom + padding),
        )

    cropped_frames = [frame.crop(crop_box) for frame in frames]

    drawable_dir = project_dir / "app" / "src" / "main" / "res" / "drawable-nodpi"
    drawable_dir.mkdir(parents=True, exist_ok=True)

    animated_target = drawable_dir / "splash_logo.gif"
    static_target = drawable_dir / "splash_system_logo.png"

    # O splash nativo do Android sempre trata o drawable como um ícone.
    # Por isso, uma imagem retangular pode parecer comprimida ou recortada.
    # Geramos um arquivo quadrado de alta resolução e mantemos a arte dentro
    # de uma área segura central, preservando totalmente a proporção.
    system_icon_canvas_size = 1024
    system_icon_safe_size = 640
    first_frame = cropped_frames[0]

    scale = min(
        system_icon_safe_size / max(1, first_frame.width),
        system_icon_safe_size / max(1, first_frame.height),
        1.0,
    )

    icon_width = max(1, round(first_frame.width * scale))
    icon_height = max(1, round(first_frame.height * scale))

    if (icon_width, icon_height) != first_frame.size:
        icon_art = first_frame.resize(
            (icon_width, icon_height),
            Image.Resampling.LANCZOS,
        )
    else:
        icon_art = first_frame

    system_icon = Image.new(
        "RGBA",
        (system_icon_canvas_size, system_icon_canvas_size),
        (255, 255, 255, 0),
    )

    icon_x = (system_icon_canvas_size - icon_width) // 2
    icon_y = (system_icon_canvas_size - icon_height) // 2
    system_icon.alpha_composite(icon_art, (icon_x, icon_y))
    system_icon.save(static_target, "PNG", optimize=True)

    cropped_frames[0].save(
        animated_target,
        save_all=True,
        append_images=cropped_frames[1:],
        duration=durations,
        loop=int(image.info.get("loop", 0) or 0),
        disposal=2,
        optimize=False,
    )

    output_width, output_height = cropped_frames[0].size
    total_duration_ms = max(0, sum(durations))

    print(
        "Splash Android preparada: "
        f"{src} -> {animated_target} ({output_width}x{output_height}, "
        f"{frame_count} frames de origem, {total_duration_ms} ms totais)"
    )

    return output_width, output_height, total_duration_ms


def create_android_project(
    out_dir: Path,
    url: str,
    app_name: str,
    package: str,
    version_code: int,
    version_name: str,
    allow_http: bool,
    agp_version: str,
    compile_sdk: int,
    min_sdk: int,
    target_sdk: int,
    firebase_json: str | None = None,
    push_register_url: str = "",
    firebase_bom_version: str = DEFAULT_FIREBASE_BOM_VERSION,
    google_services_version: str = DEFAULT_GOOGLE_SERVICES_VERSION,
    splash_gif: str | None = None,
):
    validate_package(package)
    parsed = validate_url(url)

    enable_splash = bool(splash_gif)
    splash_duration_ms = 0

    if enable_splash:
        splash_path = Path(splash_gif).expanduser().resolve()

        if not splash_path.exists():
            raise SystemExit(f"GIF da splash não encontrado: {splash_path}")

    if parsed.scheme == "http":
        allow_http = True

    enable_fcm = bool(firebase_json)
    firebase_config_path = validate_firebase_json(firebase_json, package)

    project_name = safe_project_name(app_name)
    project_dir = out_dir / f"{project_name}_android"

    if enable_splash and splash_gif:
        _, _, detected_splash_duration_ms = prepare_android_splash(project_dir, splash_gif)
        splash_duration_ms = max(3000, detected_splash_duration_ms)

    android_cleartext = "true" if allow_http else "false"
    app_name_xml = html.escape(app_name, quote=True)
    java_dir = project_dir / "app" / "src" / "main" / "java" / package_to_path(package)

    google_services_root_plugin = (
        f"\n            id 'com.google.gms.google-services' version '{google_services_version}' apply false"
        if enable_fcm else ""
    )
    google_services_app_plugin = "\n            id 'com.google.gms.google-services'" if enable_fcm else ""

    firebase_dependencies = (
        f"""
            implementation platform('com.google.firebase:firebase-bom:{firebase_bom_version}')
            implementation 'com.google.firebase:firebase-messaging'
        """
        if enable_fcm else ""
    )

    androidx_core_dependency = """
                implementation 'androidx.core:core:1.13.1'
    """

    splash_dependencies = (
        """
                implementation 'androidx.core:core-splashscreen:1.0.1'
                implementation 'pl.droidsonroids.gif:android-gif-drawable:1.2.32'
        """
        if enable_splash else ""
    )

    dependencies_block = f"""
            dependencies {{
            {androidx_core_dependency}
            {splash_dependencies}
            {firebase_dependencies}
            }}
            """

    android_use_androidx = "true"

    fcm_manifest_permission = (
        '            <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />\n'
        if enable_fcm else ""
    )

    fcm_manifest_service = (
        """
                <service
                    android:name=".MyFirebaseMessagingService"
                    android:exported="false">
                    <intent-filter>
                        <action android:name="com.google.firebase.MESSAGING_EVENT" />
                    </intent-filter>
                </service>
                <meta-data
                    android:name="com.google.firebase.messaging.default_notification_channel_id"
                    android:value="pirecal_portaria" />
        """
        if enable_fcm else ""
    )

    fcm_java_imports = (
        """
    import android.Manifest;
    import android.app.NotificationChannel;
    import android.app.NotificationManager;
    import android.content.Context;
    import android.content.pm.PackageManager;
    import android.webkit.JavascriptInterface;
    import org.json.JSONObject;
    import com.google.firebase.messaging.FirebaseMessaging;
        """
        if enable_fcm else ""
    )

    fcm_java_fields = (
        """
        private static final int NOTIFICATION_PERMISSION_REQUEST_CODE = 9104;
        private static final String FIREBASE_CHANNEL_ID = "pirecal_portaria";
        private static final String FIREBASE_CHANNEL_NAME = "Portaria Digital";
        """
        if enable_fcm else ""
    )

    fcm_setup_calls = (
        """
            createFirebaseNotificationChannel();
            requestNotificationPermissionIfNeeded();
            installFirebaseMessagingBridge();
        """
        if enable_fcm else ""
    )

    fcm_java_methods = (
        """
        private void createFirebaseNotificationChannel() {
            if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
                return;
            }

            NotificationManager manager =
                (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
            if (manager == null || manager.getNotificationChannel(FIREBASE_CHANNEL_ID) != null) {
                return;
            }

            manager.createNotificationChannel(new NotificationChannel(
                FIREBASE_CHANNEL_ID,
                FIREBASE_CHANNEL_NAME,
                NotificationManager.IMPORTANCE_DEFAULT
            ));
        }

        private void requestNotificationPermissionIfNeeded() {
            if (
                Build.VERSION.SDK_INT >= 33 &&
                checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
            ) {
                requestPermissions(
                    new String[] { Manifest.permission.POST_NOTIFICATIONS },
                    NOTIFICATION_PERMISSION_REQUEST_CODE
                );
            }
        }

        private void installFirebaseMessagingBridge() {
            webView.addJavascriptInterface(new AndroidBridge(), "AndroidBridge");

            FirebaseMessaging.getInstance().getToken().addOnCompleteListener(task -> {
                if (!task.isSuccessful()) {
                    return;
                }

                String token = task.getResult();

                if (token == null || token.trim().isEmpty()) {
                    return;
                }

                PushRegistrar.saveToken(getApplicationContext(), token);
                PushRegistrar.tryRegister(getApplicationContext());

                String script =
                    "window.dispatchEvent(new CustomEvent('fcmTokenReady',{detail:{token:" +
                    JSONObject.quote(token) +
                    ",platform:'android'}}));";

                webView.post(() -> webView.evaluateJavascript(script, null));
            });
        }

        public class AndroidBridge {
            @JavascriptInterface
            public void registerLoggedUser(String userId) {
                PushRegistrar.saveUserId(getApplicationContext(), userId, null);
                PushRegistrar.tryRegister(getApplicationContext());
            }

            @JavascriptInterface
            public void registerLoggedUserWithAuth(String userId, String bearerToken) {
                PushRegistrar.saveUserId(getApplicationContext(), userId, bearerToken);
                PushRegistrar.tryRegister(getApplicationContext());
            }

            @JavascriptInterface
            public String getFcmToken() {
                return PushRegistrar.getToken(getApplicationContext());
            }

            @JavascriptInterface
            public String getPlatform() {
                return "android";
            }

            @JavascriptInterface
            public String getAppVersion() {
                return BuildConfig.VERSION_NAME;
            }
        }
        """
        if enable_fcm else ""
    )


    splash_manifest_theme = (
        '\n                    android:theme="@style/AppTheme.Starting"'
        if enable_splash else ""
    )

    splash_starting_style = (
        """
            <style name="AppTheme.Starting" parent="Theme.SplashScreen">
                <item name="windowSplashScreenBackground">#FFFFFF</item>
                <item name="windowSplashScreenAnimatedIcon">@drawable/splash_system_logo</item>
                <item name="postSplashScreenTheme">@style/AppTheme</item>

                <item name="android:statusBarColor">#FFFFFF</item>
                <item name="android:navigationBarColor">#FFFFFF</item>
                <item name="android:windowLightStatusBar">true</item>
                <item name="android:windowLightNavigationBar">true</item>
                <item name="android:enforceStatusBarContrast">false</item>
                <item name="android:enforceNavigationBarContrast">false</item>
            </style>
        """
        if enable_splash else ""
    )

    splash_java_imports = (
        """
    import android.view.Gravity;
    import android.widget.ImageView;
    import androidx.core.splashscreen.SplashScreen;
    import pl.droidsonroids.gif.AnimationListener;
    import pl.droidsonroids.gif.GifDrawable;
    import pl.droidsonroids.gif.GifImageView;
        """
        if enable_splash else ""
    )

    splash_java_fields = (
        """
        private static final long MIN_SPLASH_DURATION_MS = __SPLASH_DURATION_MS__L;
        private static final long SPLASH_END_HOLD_MS = 100L;
        private static final long SPLASH_WEBVIEW_WARMUP_MS = 120L;
        private static final long INITIAL_WEBVIEW_DELAY_MS = 180L;
        private View splashOverlay;
        private long splashAnimationStartedAt;
        private boolean splashGifReady;
        private boolean splashDismissRequested;
        private boolean splashDismissScheduled;
        private boolean initialPageLoadRequested;
        private boolean initialPageLoadStarted;
        private GifDrawable splashGifDrawable;
        """
        if enable_splash else ""
    )

    splash_pre_super = (
        """
            SplashScreen systemSplash = SplashScreen.installSplashScreen(this);
            // Nunca mantenha a splash nativa aguardando a WebView. Ela deve sair
            // assim que a primeira tela da Activity estiver pronta.
            systemSplash.setKeepOnScreenCondition(() -> false);
        """
        if enable_splash else ""
    )

    splash_initial_system_bars = (
        """
            window.setStatusBarColor(Color.WHITE);
            window.setNavigationBarColor(Color.WHITE);

            int splashSystemUiFlags = View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                splashSystemUiFlags |= View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            }

            window.getDecorView().setSystemUiVisibility(splashSystemUiFlags);
        """
        if enable_splash
        else """
            window.setStatusBarColor(Color.parseColor("#002458"));
            window.setNavigationBarColor(Color.parseColor("#002458"));
            window.getDecorView().setSystemUiVisibility(0);
        """
    )

    splash_show_call = (
        """
            showAnimatedSplash(root);
        """
        if enable_splash else ""
    )

    splash_webview_hidden = (
        "            webView.setVisibility(View.INVISIBLE);"
        if enable_splash else ""
    )

    page_commit_callback = (
        """
                @Override
                public void onPageCommitVisible(WebView view, String url) {
                    super.onPageCommitVisible(view, url);
                    hideAnimatedSplash();
                }
        """
        if enable_splash else ""
    )

    page_finished_calls = []
    if enable_splash:
        page_finished_calls.append("hideAnimatedSplash();")
    if enable_fcm:
        page_finished_calls.append("PushRegistrar.tryRegister(getApplicationContext());")

    splash_webview_callbacks = (
        """
%s

                @Override
                public void onPageFinished(WebView view, String url) {
                    super.onPageFinished(view, url);
                    %s
                }
        """ % (page_commit_callback, ' '.join(page_finished_calls))
        if page_finished_calls else ""
    )

    splash_error_call = "hideAnimatedSplash();" if enable_splash else ""

    splash_initial_page_load = (
        "                requestInitialPageLoad();"
        if enable_splash
        else "                webView.loadUrl(HOME_URL);"
    )

    splash_java_methods = (
        """
        private void showAnimatedSplash(FrameLayout root) {
            splashAnimationStartedAt = 0L;
            splashGifReady = false;
            splashDismissRequested = false;
            splashDismissScheduled = false;
            initialPageLoadRequested = false;
            initialPageLoadStarted = false;
            splashGifDrawable = null;

            // A WebView continua carregando, mas não disputa desenho com o GIF.
            // Ela volta a ficar visível pouco antes do fade da splash.
            if (webView != null) {
                webView.setVisibility(View.INVISIBLE);
            }

            FrameLayout overlay = new FrameLayout(this);
            overlay.setBackgroundColor(Color.WHITE);
            overlay.setClickable(true);
            overlay.setFocusable(true);

            GifImageView logoView = new GifImageView(this);
            logoView.setAdjustViewBounds(true);
            logoView.setScaleType(ImageView.ScaleType.FIT_CENTER);
            logoView.setContentDescription(null);

            int screenWidth = getResources().getDisplayMetrics().widthPixels;
            int screenHeight = getResources().getDisplayMetrics().heightPixels;

            int targetWidth = Math.min(
                Math.round(screenWidth * 0.82f),
                dpToPx(560)
            );

            int maximumHeight = Math.min(
                Math.round(screenHeight * 0.52f),
                dpToPx(420)
            );

            logoView.setMaxHeight(maximumHeight);

            FrameLayout.LayoutParams logoParams = new FrameLayout.LayoutParams(
                targetWidth,
                ViewGroup.LayoutParams.WRAP_CONTENT,
                Gravity.CENTER
            );

            overlay.addView(logoView, logoParams);

            FrameLayout.LayoutParams overlayParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                ViewGroup.LayoutParams.MATCH_PARENT
            );

            root.addView(overlay, overlayParams);
            splashOverlay = overlay;

            try {
                GifDrawable gifDrawable = new GifDrawable(
                    getResources(),
                    R.drawable.splash_logo
                );

                splashGifDrawable = gifDrawable;

                /*
                 * O carregamento do portal pode levar mais que os 3,75 s do GIF.
                 * Portanto, a animação repete enquanto a página inicial não está
                 * pronta. No código anterior ela executava uma única vez e ficava
                 * congelada no último quadro até a tela de login aparecer.
                 */
                gifDrawable.setLoopCount(1);
                gifDrawable.stop();
                logoView.setImageDrawable(gifDrawable);

                gifDrawable.addAnimationListener(new AnimationListener() {
                    @Override
                    public void onAnimationCompleted(int loopNumber) {
                        // O fade continua controlado pelo carregamento da WebView.
                        // Este listener apenas mantém o ciclo de vida explícito.
                    }
                });

                logoView.post(() -> {
                    markSplashAnimationStarted();
                    gifDrawable.seekToFrame(0);
                    gifDrawable.start();
                });
            } catch (Exception exception) {
                logoView.setImageResource(R.drawable.splash_system_logo);
                markSplashAnimationStarted();
            }
        }

        private void markSplashAnimationStarted() {
            if (splashGifReady) {
                return;
            }

            splashAnimationStartedAt = System.currentTimeMillis();
            splashGifReady = true;
            startInitialPageLoadIfReady();
            scheduleSplashDismissIfReady();
        }

        private void requestInitialPageLoad() {
            initialPageLoadRequested = true;
            startInitialPageLoadIfReady();
        }

        private void startInitialPageLoadIfReady() {
            if (
                !initialPageLoadRequested ||
                initialPageLoadStarted ||
                !splashGifReady ||
                webView == null
            ) {
                return;
            }

            initialPageLoadStarted = true;

            // Dá alguns quadros de vantagem ao GIF antes de iniciar o trabalho
            // pesado da WebView. Isso reduz as travadinhas no começo.
            webView.postDelayed(
                () -> webView.loadUrl(HOME_URL),
                INITIAL_WEBVIEW_DELAY_MS
            );
        }

        private void hideAnimatedSplash() {
            if (splashOverlay == null) {
                return;
            }

            /*
             * A página pode ficar pronta antes do GIF. Nesse caso, apenas
             * registramos o pedido e aguardamos o GIF começar para contar a
             * duração completa da animação.
             */
            splashDismissRequested = true;
            scheduleSplashDismissIfReady();
        }

        private void scheduleSplashDismissIfReady() {
            if (
                splashOverlay == null ||
                !splashGifReady ||
                !splashDismissRequested ||
                splashDismissScheduled
            ) {
                return;
            }

            splashDismissScheduled = true;

            long elapsed = System.currentTimeMillis() - splashAnimationStartedAt;
            long requiredDuration = MIN_SPLASH_DURATION_MS + SPLASH_END_HOLD_MS;
            long remaining = Math.max(0L, requiredDuration - elapsed);

            splashOverlay.postDelayed(() -> {
                if (splashOverlay == null) {
                    restoreBrandSystemBars();
                    return;
                }

                // Torna a WebView visível ainda atrás da camada branca e dá um
                // pequeno tempo para o primeiro frame ser composto antes do fade.
                if (webView != null) {
                    webView.setVisibility(View.VISIBLE);
                }

                splashOverlay.postDelayed(() -> {
                    if (splashOverlay == null) {
                        restoreBrandSystemBars();
                        return;
                    }

                    View overlayToRemove = splashOverlay;

                    overlayToRemove.animate()
                        .alpha(0f)
                        .setDuration(220L)
                        .withEndAction(() -> {
                            ViewGroup parent = (ViewGroup) overlayToRemove.getParent();

                            if (parent != null) {
                                parent.removeView(overlayToRemove);
                            }

                            if (splashOverlay == overlayToRemove) {
                                splashOverlay = null;
                            }

                            if (splashGifDrawable != null) {
                                splashGifDrawable.stop();
                                splashGifDrawable.recycle();
                                splashGifDrawable = null;
                            }

                            restoreBrandSystemBars();
                        })
                        .start();
                }, SPLASH_WEBVIEW_WARMUP_MS);
            }, remaining);
        }

        private void restoreBrandSystemBars() {
            Window window = getWindow();
            window.setStatusBarColor(Color.parseColor("#002458"));
            window.setNavigationBarColor(Color.parseColor("#002458"));
            window.getDecorView().setSystemUiVisibility(0);

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                window.setStatusBarContrastEnforced(false);
                window.setNavigationBarContrastEnforced(false);
            }
        }

        private int dpToPx(int value) {
            float density = getResources().getDisplayMetrics().density;
            return Math.round(value * density);
        }
        """
        if enable_splash else ""
    )

    write_file(
        project_dir / "settings.gradle",
        f"""
        pluginManagement {{
            repositories {{
                google()
                mavenCentral()
                gradlePluginPortal()
            }}
        }}

        dependencyResolutionManagement {{
            repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
            repositories {{
                google()
                mavenCentral()
            }}
        }}

        rootProject.name = '{project_name}'
        include ':app'
        """,
    )

    write_file(
        project_dir / "build.gradle",
        f"""
        plugins {{
            id 'com.android.application' version '{agp_version}' apply false{google_services_root_plugin}
        }}
        """,
    )

    write_file(
        project_dir / "gradle.properties",
        f"""
        org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
        android.useAndroidX={android_use_androidx}
        android.nonTransitiveRClass=true
        """,
    )

    write_file(
        project_dir / "app" / "build.gradle",
        f"""
        import java.util.Properties
        import java.io.FileInputStream

        plugins {{
            id 'com.android.application'{google_services_app_plugin}
        }}

        def keystoreProperties = new Properties()
        def keystorePropertiesFile = rootProject.file("keystore.properties")
        def hasReleaseKeystore = keystorePropertiesFile.exists()

        if (hasReleaseKeystore) {{
            keystoreProperties.load(new FileInputStream(keystorePropertiesFile))
        }}

        android {{
            namespace '{package}'
            compileSdk {compile_sdk}

            defaultConfig {{
                applicationId '{package}'
                minSdk {min_sdk}
                targetSdk {target_sdk}
                versionCode {version_code}
                versionName '{version_name}'
            }}

            buildFeatures {{
                buildConfig true
            }}

            signingConfigs {{
                release {{
                    if (hasReleaseKeystore) {{
                        storeFile rootProject.file(keystoreProperties['storeFile'])
                        storePassword keystoreProperties['storePassword']
                        keyAlias keystoreProperties['keyAlias']
                        keyPassword keystoreProperties['keyPassword']
                    }}
                }}
            }}

            buildTypes {{
                debug {{
                    debuggable true
                }}

                release {{
                    if (hasReleaseKeystore) {{
                        signingConfig signingConfigs.release
                    }}

                    minifyEnabled false
                    shrinkResources false
                }}
            }}

            compileOptions {{
                sourceCompatibility JavaVersion.VERSION_17
                targetCompatibility JavaVersion.VERSION_17
            }}
        }}

        {dependencies_block}
        """,
    )

    write_file(
        project_dir / "app" / "src" / "main" / "AndroidManifest.xml",
        f"""
        <manifest xmlns:android="http://schemas.android.com/apk/res/android">

            <queries>
                <intent>
                    <action android:name="android.media.action.IMAGE_CAPTURE" />
                </intent>
                <intent>
                    <action android:name="android.intent.action.GET_CONTENT" />
                </intent>
            </queries>

            <uses-feature
                android:name="android.hardware.camera"
                android:required="false" />

            <uses-permission android:name="android.permission.INTERNET" />
            <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />
{fcm_manifest_permission}
            <application
                android:theme="@style/AppTheme"
                android:label="@string/app_name"
                android:icon="@mipmap/ic_launcher"
                android:roundIcon="@mipmap/ic_launcher_round"
                android:usesCleartextTraffic="{android_cleartext}"
                android:hardwareAccelerated="true"
                android:resizeableActivity="true"
                android:supportsRtl="true">
{fcm_manifest_service}
                <provider
                    android:name="androidx.core.content.FileProvider"
                    android:authorities="{package}.fileprovider"
                    android:exported="false"
                    android:grantUriPermissions="true">
                    <meta-data
                        android:name="android.support.FILE_PROVIDER_PATHS"
                        android:resource="@xml/file_paths" />
                </provider>
                <activity
                    android:name=".MainActivity"{splash_manifest_theme}
                    android:exported="true"
                    android:launchMode="singleTop"
                    android:screenOrientation="fullSensor"
                    android:configChanges="orientation|screenSize|screenLayout|smallestScreenSize|keyboardHidden|uiMode">
                    <intent-filter>
                        <action android:name="android.intent.action.MAIN" />
                        <category android:name="android.intent.category.LAUNCHER" />
                    </intent-filter>
                </activity>
            </application>
        </manifest>
        """,
    )

    write_file(
        project_dir / "app" / "src" / "main" / "res" / "values" / "strings.xml",
        f"""
        <resources>
            <string name="app_name">{app_name_xml}</string>
        </resources>
        """,
    )

    write_file(
        project_dir / "app" / "src" / "main" / "res" / "values" / "colors.xml",
        """
        <resources>
            <color name="brand_primary">#002458</color>
            <color name="brand_green">#049536</color>
            <color name="brand_light">#EAEFEB</color>
            <color name="brand_blue">#0046C2</color>
            <color name="ic_launcher_background">#002458</color>
        </resources>
        """,
    )

    write_file(
        project_dir / "app" / "src" / "main" / "res" / "values" / "styles.xml",
        f"""
        <resources>
            <style name="AppTheme" parent="@android:style/Theme.Material.Light.NoActionBar">
                <item name="android:fontFamily">sans</item>
                <item name="android:windowNoTitle">true</item>
                <item name="android:windowActionBar">false</item>

                <item name="android:windowDrawsSystemBarBackgrounds">true</item>

                <item name="android:statusBarColor">#002458</item>
                <item name="android:navigationBarColor">#002458</item>

                <item name="android:windowLightStatusBar">false</item>
                <item name="android:windowLightNavigationBar">false</item>

                <item name="android:enforceStatusBarContrast">false</item>
                <item name="android:enforceNavigationBarContrast">false</item>

                <item name="android:windowDisablePreview">true</item>
            </style>
{splash_starting_style}
        </resources>
        """,
    )

    write_file(
        project_dir / "app" / "src" / "main" / "res" / "xml" / "file_paths.xml",
        """
        <paths xmlns:android="http://schemas.android.com/apk/res/android">
            <cache-path
                name="cache"
                path="." />

            <external-cache-path
                name="external_cache"
                path="." />

            <files-path
                name="files"
                path="." />

            <external-files-path
                name="external_files"
                path="." />
        </paths>
        """,
    )

    write_file(
        project_dir / "app" / "src" / "main" / "res" / "drawable" / "ic_launcher_foreground.xml",
        """
        <vector xmlns:android="http://schemas.android.com/apk/res/android"
            android:width="108dp"
            android:height="108dp"
            android:viewportWidth="108"
            android:viewportHeight="108">
            <path
                android:fillColor="#049536"
                android:pathData="M54,12C30.8,12 12,30.8 12,54s18.8,42 42,42 42,-18.8 42,-42S77.2,12 54,12z" />
            <path
                android:fillColor="#EAEFEB"
                android:pathData="M27,67L48,39l13,16 9,-12 15,24H72L60,50 48,67z" />
            <path
                android:fillColor="#002458"
                android:pathData="M27,72h58v7H27z" />
        </vector>
        """,
    )

    write_file(
        project_dir / "app" / "src" / "main" / "res" / "mipmap-anydpi-v26" / "ic_launcher.xml",
        """
        <adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
            <background android:drawable="@color/ic_launcher_background" />
            <foreground android:drawable="@drawable/ic_launcher_foreground" />
        </adaptive-icon>
        """,
    )

    write_file(
        project_dir / "app" / "src" / "main" / "res" / "mipmap-anydpi-v26" / "ic_launcher_round.xml",
        """
        <adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
            <background android:drawable="@color/ic_launcher_background" />
            <foreground android:drawable="@drawable/ic_launcher_foreground" />
        </adaptive-icon>
        """,
    )

    main_activity = """
    package __PACKAGE__;

    import android.annotation.SuppressLint;
    import android.app.Activity;
    import android.content.ActivityNotFoundException;
    import android.content.Intent;
    import android.content.ClipData;
    import android.graphics.Color;
    import android.net.Uri;
    import android.os.Bundle;
    import android.os.Build;
    import android.os.Message;
    import android.os.Environment;
    import android.provider.MediaStore;
    import android.view.View;
    import android.view.ViewGroup;
    import android.view.Window;
    import android.webkit.CookieManager;
    import android.webkit.DownloadListener;
    import android.webkit.WebChromeClient;
    import android.webkit.WebChromeClient.FileChooserParams;
    import android.webkit.WebResourceRequest;
    import android.webkit.WebResourceError;
    import android.webkit.WebResourceResponse;
    import android.webkit.WebSettings;
    import android.webkit.WebView;
    import android.webkit.WebViewClient;
    import android.webkit.ValueCallback;
    import android.widget.FrameLayout;
    import android.widget.ProgressBar;
    import androidx.core.content.FileProvider;
__SPLASH_IMPORTS__
    import java.io.File;
    import java.io.IOException;
    import java.net.HttpURLConnection;
    import java.net.URL;
    import java.text.SimpleDateFormat;
    import java.util.Date;
    import java.util.Locale;
    
__FCM_IMPORTS__

    public class MainActivity extends Activity {
        private static final String HOME_URL = __URL__;
        private static final String LOGOUT_URL = __LOGOUT_URL__;
        private WebView webView;
        private ProgressBar progressBar;
        private static final int FILE_CHOOSER_REQUEST_CODE = 5001;
        private ValueCallback<Uri[]> filePathCallback;
        private String cameraPhotoUri;
__SPLASH_FIELDS__
__FCM_FIELDS__

        @SuppressLint("SetJavaScriptEnabled")
        @Override
        protected void onCreate(Bundle savedInstanceState) {
__SPLASH_PRE_SUPER__
            super.onCreate(savedInstanceState);
            requestWindowFeature(Window.FEATURE_NO_TITLE);

            Window window = getWindow();

__SPLASH_INITIAL_SYSTEM_BARS__

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                window.setStatusBarContrastEnforced(false);
                window.setNavigationBarContrastEnforced(false);
            }

            FrameLayout root = new FrameLayout(this);
            root.setBackgroundColor(Color.WHITE);

            /*
             * Mostra primeiro a camada animada e só depois instancia a WebView.
             * A criação da WebView pode ser relativamente pesada em alguns
             * aparelhos e, se ela ocorrer antes do primeiro draw, o Android
             * mantém a logo estática do splash nativo por tempo demais.
             */
            setContentView(root);
__SPLASH_SHOW_CALL__

            webView = new WebView(this);
__SPLASH_WEBVIEW_HIDDEN__
            progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
            progressBar.setMax(100);
            progressBar.setProgress(0);

            root.addView(
                webView,
                0,
                new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT
                )
            );

            FrameLayout.LayoutParams progressParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                8
            );

            // Em apps com splash, o índice 1 mantém a barra atrás da camada branca.
            int progressIndex = Math.min(1, root.getChildCount());
            root.addView(progressBar, progressIndex, progressParams);

            WebSettings settings = webView.getSettings();
            settings.setJavaScriptEnabled(true);
            settings.setDomStorageEnabled(true);
            settings.setDatabaseEnabled(true);
            settings.setLoadWithOverviewMode(true);
            settings.setUseWideViewPort(true);
            settings.setSupportZoom(false);
            settings.setBuiltInZoomControls(false);
            settings.setDisplayZoomControls(false);
            settings.setMediaPlaybackRequiresUserGesture(false);
            settings.setCacheMode(WebSettings.LOAD_DEFAULT);
            settings.setSupportMultipleWindows(true);
            settings.setJavaScriptCanOpenWindowsAutomatically(true);
__FCM_SETUP_CALLS__

            CookieManager cookieManager = CookieManager.getInstance();
            cookieManager.setAcceptCookie(true);
            cookieManager.setAcceptThirdPartyCookies(webView, true);

            webView.setWebViewClient(new WebViewClient() {
                @Override
                public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                    return handleUrlInsideMainWebView(request.getUrl());
                }

                @SuppressWarnings("deprecation")
                @Override
                public boolean shouldOverrideUrlLoading(WebView view, String url) {
                    return handleUrlInsideMainWebView(Uri.parse(url));
                }

__SPLASH_WEBVIEW_CALLBACKS__

                @Override
                public void onReceivedError(
                    WebView view,
                    WebResourceRequest request,
                    WebResourceError error
                ) {
                    super.onReceivedError(view, request, error);

                    if (request != null && request.isForMainFrame()) {
__SPLASH_ERROR_CALL__
                        showWebViewErrorPage(
                            "Não foi possível conectar",
                            "Verifique sua conexão com a internet ou tente novamente em alguns instantes.",
                            request.getUrl() != null ? request.getUrl().toString() : HOME_URL
                        );
                    }
                }

                @Override
                public void onReceivedHttpError(
                    WebView view,
                    WebResourceRequest request,
                    WebResourceResponse errorResponse
                ) {
                    super.onReceivedHttpError(view, request, errorResponse);

                    if (request == null || !request.isForMainFrame()) {
                        return;
                    }

                    int statusCode = errorResponse != null ? errorResponse.getStatusCode() : 0;

                    if (statusCode >= 400) {
__SPLASH_ERROR_CALL__
                        showWebViewErrorPage(
                            "Sistema indisponível",
                            "O servidor retornou erro " + statusCode + ". Tente novamente em alguns instantes.",
                            request.getUrl() != null ? request.getUrl().toString() : HOME_URL
                        );
                    }
                }

                private boolean handleUrlInsideMainWebView(Uri uri) {
                    String scheme = uri.getScheme() == null ? "" : uri.getScheme().toLowerCase();

                    if (
                        scheme.equals("tel") ||
                        scheme.equals("mailto") ||
                        scheme.equals("whatsapp") ||
                        scheme.equals("intent")
                    ) {
                        openExternalBrowser(uri);
                        return true;
                    }

                    /*
                    * http/https normais continuam dentro do app.
                    * Links target="_blank" são tratados no WebChromeClient.onCreateWindow().
                    */
                    return false;
                }
            });

            webView.setWebChromeClient(new WebChromeClient() {
                @Override
                public void onProgressChanged(WebView view, int newProgress) {
                    progressBar.setProgress(newProgress);
                    progressBar.setVisibility(newProgress >= 100 ? View.GONE : View.VISIBLE);
                }

                @Override
                public boolean onShowFileChooser(
                    WebView webView,
                    ValueCallback<Uri[]> filePathCallback,
                    FileChooserParams fileChooserParams
                ) {
                    if (MainActivity.this.filePathCallback != null) {
                        MainActivity.this.filePathCallback.onReceiveValue(null);
                    }

                    MainActivity.this.filePathCallback = filePathCallback;

                    Intent cameraIntent = null;

                    try {
                        File photoFile = createImageFile();

                        if (photoFile != null) {
                            Uri photoUri = FileProvider.getUriForFile(
                                MainActivity.this,
                                getPackageName() + ".fileprovider",
                                photoFile
                            );

                            cameraPhotoUri = photoUri.toString();

                            cameraIntent = new Intent(MediaStore.ACTION_IMAGE_CAPTURE);
                            cameraIntent.putExtra(MediaStore.EXTRA_OUTPUT, photoUri);
                            cameraIntent.setClipData(ClipData.newRawUri("camera", photoUri));
                            cameraIntent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                            cameraIntent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION);
                        }
                    } catch (Exception ignored) {
                        cameraIntent = null;
                        cameraPhotoUri = null;
                    }

                    Intent contentIntent;

                    try {
                        contentIntent = fileChooserParams.createIntent();
                    } catch (Exception exception) {
                        contentIntent = new Intent(Intent.ACTION_GET_CONTENT);
                        contentIntent.addCategory(Intent.CATEGORY_OPENABLE);
                        contentIntent.setType("*/*");
                    }

                    try {
                        /*
                        * Se o input vier com capture, exemplo:
                        * <input type="file" accept="image/*" capture="environment">
                        * abre direto a câmera.
                        */
                        if (fileChooserParams.isCaptureEnabled() && cameraIntent != null) {
                            startActivityForResult(cameraIntent, FILE_CHOOSER_REQUEST_CODE);
                            return true;
                        }

                        Intent chooserIntent = Intent.createChooser(contentIntent, "Selecionar arquivo");

                        if (cameraIntent != null) {
                            chooserIntent.putExtra(
                                Intent.EXTRA_INITIAL_INTENTS,
                                new Intent[] { cameraIntent }
                            );
                        }

                        startActivityForResult(chooserIntent, FILE_CHOOSER_REQUEST_CODE);
                    } catch (Exception exception) {
                        MainActivity.this.filePathCallback = null;
                        filePathCallback.onReceiveValue(null);
                        return false;
                    }

                    return true;
                }

                @Override
                public boolean onCreateWindow(
                    WebView view,
                    boolean isDialog,
                    boolean isUserGesture,
                    Message resultMsg
                ) {
                    WebView.HitTestResult hitTestResult = view.getHitTestResult();
                    String targetUrl = hitTestResult != null ? hitTestResult.getExtra() : null;

                    if (targetUrl != null && !targetUrl.trim().isEmpty()) {
                        openExternalBrowser(Uri.parse(targetUrl));
                        return false;
                    }

                    WebView popupWebView = new WebView(MainActivity.this);

                    popupWebView.setWebViewClient(new WebViewClient() {
                        @Override
                        public boolean shouldOverrideUrlLoading(WebView popupView, WebResourceRequest request) {
                            openExternalBrowser(request.getUrl());
                            popupView.destroy();
                            return true;
                        }

                        @SuppressWarnings("deprecation")
                        @Override
                        public boolean shouldOverrideUrlLoading(WebView popupView, String url) {
                            openExternalBrowser(Uri.parse(url));
                            popupView.destroy();
                            return true;
                        }

                        @Override
                        public void onPageStarted(WebView popupView, String url, android.graphics.Bitmap favicon) {
                            openExternalBrowser(Uri.parse(url));
                            popupView.stopLoading();
                            popupView.destroy();
                        }
                    });

                    WebView.WebViewTransport transport = (WebView.WebViewTransport) resultMsg.obj;
                    transport.setWebView(popupWebView);
                    resultMsg.sendToTarget();

                    return true;
                }
            });

            webView.setDownloadListener(new DownloadListener() {
                @Override
                public void onDownloadStart(
                    String url,
                    String userAgent,
                    String contentDisposition,
                    String mimetype,
                    long contentLength
                ) {
                    openExternalBrowser(Uri.parse(url));
                }
            });

            if (savedInstanceState != null) {
                webView.restoreState(savedInstanceState);
            } else {
                clearSessionBeforeStart();
__INITIAL_PAGE_LOAD__
            }
        }

        @Override
        protected void onActivityResult(int requestCode, int resultCode, Intent data) {
            super.onActivityResult(requestCode, resultCode, data);

            if (requestCode != FILE_CHOOSER_REQUEST_CODE) {
                return;
            }

            if (filePathCallback == null) {
                return;
            }

            Uri[] results = null;

            if (resultCode == RESULT_OK) {
                if (data == null || data.getData() == null) {
                    if (cameraPhotoUri != null && !cameraPhotoUri.trim().isEmpty()) {
                        results = new Uri[] { Uri.parse(cameraPhotoUri) };
                    }
                } else {
                    String dataString = data.getDataString();

                    if (data.getClipData() != null) {
                        int count = data.getClipData().getItemCount();
                        results = new Uri[count];

                        for (int i = 0; i < count; i++) {
                            results[i] = data.getClipData().getItemAt(i).getUri();
                        }
                    } else if (dataString != null) {
                        results = new Uri[] { Uri.parse(dataString) };
                    }
                }
            }

            filePathCallback.onReceiveValue(results);
            filePathCallback = null;
            cameraPhotoUri = null;
        }

        private File createImageFile() throws IOException {
            String timeStamp = new SimpleDateFormat(
                "yyyyMMdd_HHmmss",
                Locale.getDefault()
            ).format(new Date());

            String imageFileName = "Pirecal_" + timeStamp + "_";

            File storageDir = getExternalFilesDir(Environment.DIRECTORY_PICTURES);

            if (storageDir == null) {
                storageDir = getCacheDir();
            }

            return File.createTempFile(
                imageFileName,
                ".jpg",
                storageDir
            );
        }

        @Override
        protected void onSaveInstanceState(Bundle outState) {
            super.onSaveInstanceState(outState);
            if (webView != null) {
                webView.saveState(outState);
            }
        }

        @Override
        public void onBackPressed() {
            if (webView != null && webView.canGoBack()) {
                webView.goBack();
            } else {
                super.onBackPressed();
            }
        }

        @Override
        protected void onNewIntent(Intent intent) {
            super.onNewIntent(intent);
            setIntent(intent);

            if (
                intent != null &&
                "OPEN_NOTIFICATION".equals(intent.getAction())
            ) {
                if (webView != null) {
                    webView.loadUrl(HOME_URL);
                }
            }
        }

        @Override
        public void onConfigurationChanged(
            android.content.res.Configuration newConfig
        ) {
            super.onConfigurationChanged(newConfig);

            if (webView != null) {
                webView.requestLayout();
                webView.invalidate();
            }
        }

        @Override
        protected void onDestroy() {
            if (webView != null) {
                webView.destroy();
                webView = null;
            }

            super.onDestroy();
        }

        private void openExternalBrowser(Uri uri) {
            if (uri == null) {
                return;
            }

            try {
                Intent intent = new Intent(Intent.ACTION_VIEW, uri);
                intent.addCategory(Intent.CATEGORY_BROWSABLE);
                startActivity(intent);
            } catch (ActivityNotFoundException ignored) {
            }
        }

        private void showWebViewErrorPage(String title, String message, String retryUrl) {
            if (webView == null) {
                return;
            }

            if (retryUrl == null || retryUrl.trim().isEmpty()) {
                retryUrl = HOME_URL;
            }

            String safeTitle = title == null ? "Página indisponível" : title;
            String safeMessage = message == null ? "Não foi possível carregar o portal." : message;
            String safeRetryUrl = retryUrl
                .replace("\\\\", "\\\\\\\\")
                .replace("'", "\\\\'");

            String html =
                "<!DOCTYPE html>" +
                "<html lang='pt-BR'>" +
                "<head>" +
                "<meta charset='UTF-8'>" +
                "<meta name='viewport' content='width=device-width, initial-scale=1.0, viewport-fit=cover'>" +
                "<style>" +
                ":root{" +
                "--brand-navy:#002458;" +
                "--brand-blue:#0046C2;" +
                "--brand-green:#049536;" +
                "--brand-mist:#EAEFEB;" +
                "--white:#ffffff;" +
                "}" +
                "*{box-sizing:border-box;margin:0;padding:0;font-family:Inter,Roboto,Arial,sans-serif;}" +
                "html,body{width:100%;height:100%;}" +
                "body{" +
                "min-height:100dvh;" +
                "display:flex;" +
                "align-items:center;" +
                "justify-content:center;" +
                "padding:28px;" +
                "color:var(--white);" +
                "background:" +
                "radial-gradient(circle at 18% 12%, rgba(4,149,54,.22), transparent 18rem)," +
                "linear-gradient(135deg,var(--brand-navy),var(--brand-blue));" +
                "}" +
                ".card{" +
                "width:min(100%,430px);" +
                "padding:28px;" +
                "border-radius:30px;" +
                "background:rgba(255,255,255,.94);" +
                "color:#101828;" +
                "text-align:center;" +
                "box-shadow:0 30px 80px rgba(0,20,50,.34);" +
                "border:1px solid rgba(255,255,255,.65);" +
                "}" +
                ".icon{" +
                "width:72px;height:72px;" +
                "margin:0 auto 18px;" +
                "border-radius:24px;" +
                "display:flex;" +
                "align-items:center;" +
                "justify-content:center;" +
                "background:linear-gradient(135deg,var(--brand-navy),var(--brand-blue));" +
                "color:var(--white);" +
                "font-size:34px;" +
                "font-weight:900;" +
                "}" +
                "h1{" +
                "font-size:1.55rem;" +
                "line-height:1.08;" +
                "letter-spacing:-.04em;" +
                "color:var(--brand-navy);" +
                "margin-bottom:10px;" +
                "}" +
                "p{" +
                "font-size:.96rem;" +
                "line-height:1.45;" +
                "font-weight:650;" +
                "color:#667085;" +
                "margin-bottom:20px;" +
                "}" +
                "button{" +
                "width:100%;" +
                "min-height:50px;" +
                "border:0;" +
                "border-radius:18px;" +
                "font-size:1rem;" +
                "font-weight:900;" +
                "color:var(--white);" +
                "background:linear-gradient(135deg,var(--brand-green),#12B852);" +
                "box-shadow:0 14px 24px rgba(4,149,54,.24);" +
                "}" +
                ".hint{" +
                "display:block;" +
                "margin-top:14px;" +
                "font-size:.76rem;" +
                "font-weight:800;" +
                "color:#8A94A6;" +
                "}" +
                "</style>" +
                "</head>" +
                "<body>" +
                "<main class='card'>" +
                "<div class='icon'>!</div>" +
                "<h1>" + safeTitle + "</h1>" +
                "<p>" + safeMessage + "</p>" +
                "<button onclick=\\\"window.location.href='" + safeRetryUrl + "'\\\">Tentar novamente</button>" +
                "<span class='hint'>Pirecal Agendamento</span>" +
                "</main>" +
                "</body>" +
                "</html>";

            webView.loadDataWithBaseURL(
                HOME_URL,
                html,
                "text/html",
                "UTF-8",
                null
            );
        }

        private void logoutServerSession() {
        try {
            CookieManager cookieManager = CookieManager.getInstance();
            String cookies = cookieManager.getCookie(HOME_URL);

            new Thread(() -> {
                HttpURLConnection connection = null;

                try {
                    URL url = new URL(LOGOUT_URL);
                    connection = (HttpURLConnection) url.openConnection();
                    connection.setRequestMethod("GET");
                    connection.setConnectTimeout(3000);
                    connection.setReadTimeout(3000);

                    if (cookies != null && !cookies.trim().isEmpty()) {
                        connection.setRequestProperty("Cookie", cookies);
                    }

                    connection.getResponseCode();
                } catch (Exception ignored) {
                } finally {
                    if (connection != null) {
                        connection.disconnect();
                    }
                }
            }).start();

        } catch (Exception ignored) {
        }
    }

    private void clearWebViewSessionCookies() {
        try {
            CookieManager cookieManager = CookieManager.getInstance();
            cookieManager.removeAllCookies(null);
            cookieManager.flush();
        } catch (Exception ignored) {
        }
    }

    private void clearSessionBeforeStart() {
        try {
            CookieManager cookieManager = CookieManager.getInstance();

            cookieManager.removeSessionCookies(null);
            cookieManager.flush();

        } catch (Exception ignored) {
        }
    }

__SPLASH_METHODS__

__FCM_METHODS__
    }
    """

    main_activity = (
        textwrap.dedent(main_activity)
        .replace("__PACKAGE__", package)
        .replace("__URL__", json.dumps(url))
        .replace("__LOGOUT_URL__", json.dumps(f"{parsed.scheme}://{parsed.netloc}/logout.php"))
        .replace("__SPLASH_IMPORTS__", textwrap.dedent(splash_java_imports).rstrip())
        .replace("__SPLASH_FIELDS__", textwrap.dedent(splash_java_fields).rstrip())
        .replace("__SPLASH_PRE_SUPER__", textwrap.dedent(splash_pre_super).rstrip())
        .replace("__SPLASH_INITIAL_SYSTEM_BARS__", textwrap.dedent(splash_initial_system_bars).rstrip())
        .replace("__SPLASH_SHOW_CALL__", textwrap.dedent(splash_show_call).rstrip())
        .replace("__SPLASH_WEBVIEW_HIDDEN__", splash_webview_hidden)
        .replace("__SPLASH_WEBVIEW_CALLBACKS__", textwrap.dedent(splash_webview_callbacks).rstrip())
        .replace("__SPLASH_ERROR_CALL__", splash_error_call)
        .replace("__INITIAL_PAGE_LOAD__", splash_initial_page_load)
        .replace("__SPLASH_METHODS__", textwrap.dedent(splash_java_methods).rstrip())
        .replace("__SPLASH_DURATION_MS__", str(splash_duration_ms or 3000))
        .replace("__FCM_IMPORTS__", textwrap.dedent(fcm_java_imports).rstrip())
        .replace("__FCM_FIELDS__", textwrap.dedent(fcm_java_fields).rstrip())
        .replace("__FCM_SETUP_CALLS__", textwrap.dedent(fcm_setup_calls).rstrip())
        .replace("__FCM_METHODS__", textwrap.dedent(fcm_java_methods).rstrip())
    )

    write_file(java_dir / "MainActivity.java", main_activity)

    if enable_fcm:
        if firebase_config_path:
            shutil.copy2(firebase_config_path, project_dir / "app" / "google-services.json")

        write_file(
            java_dir / "PushConfig.java",
            f"""
            package {package};

            public final class PushConfig {{
                public static final String PUSH_REGISTER_URL = {json.dumps(push_register_url or "")};

                private PushConfig() {{
                }}
            }}
            """,
        )

        write_file(
            java_dir / "PushRegistrar.java",
            f"""
            package {package};

            import android.content.Context;
            import android.content.SharedPreferences;
            import android.os.Build;
            import android.webkit.CookieManager;

            import org.json.JSONObject;

            import java.io.OutputStream;
            import java.net.HttpURLConnection;
            import java.net.URL;
            import java.nio.charset.StandardCharsets;

            public final class PushRegistrar {{
                private static final String PREFS = "pirecal_push";
                private static final String KEY_USER_ID = "user_id";
                private static final String KEY_TOKEN = "fcm_token";
                private static final String KEY_AUTH = "auth_token";

                private PushRegistrar() {{
                }}

                public static void saveToken(Context context, String token) {{
                    if (token == null || token.trim().isEmpty()) {{
                        return;
                    }}

                    prefs(context).edit().putString(KEY_TOKEN, token.trim()).apply();
                }}

                public static String getToken(Context context) {{
                    return prefs(context).getString(KEY_TOKEN, "");
                }}

                public static void saveUserId(Context context, String userId, String bearerToken) {{
                    if (userId == null || userId.trim().isEmpty()) {{
                        return;
                    }}

                    SharedPreferences.Editor editor = prefs(context).edit();
                    editor.putString(KEY_USER_ID, userId.trim());

                    if (bearerToken != null && !bearerToken.trim().isEmpty()) {{
                        editor.putString(KEY_AUTH, bearerToken.trim());
                    }}

                    editor.apply();
                }}

                public static void tryRegister(Context context) {{
                    String endpoint = PushConfig.PUSH_REGISTER_URL;

                    if (endpoint == null || endpoint.trim().isEmpty()) {{
                        return;
                    }}

                    String userId = prefs(context).getString(KEY_USER_ID, "");
                    String token = prefs(context).getString(KEY_TOKEN, "");
                    String authToken = prefs(context).getString(KEY_AUTH, "");

                    if (token == null || token.trim().isEmpty()) {{
                        return;
                    }}

                    String webViewCookies = "";
                    try {{
                        CookieManager cookieManager = CookieManager.getInstance();
                        cookieManager.flush();
                        String currentCookies = cookieManager.getCookie(endpoint);
                        webViewCookies = currentCookies == null ? "" : currentCookies.trim();
                    }} catch (Exception ignored) {{
                    }}

                    if (
                        (userId == null || userId.trim().isEmpty()) &&
                        (authToken == null || authToken.trim().isEmpty()) &&
                        webViewCookies.isEmpty()
                    ) {{
                        return;
                    }}

                    final String sessionCookies = webViewCookies;

                    new Thread(() -> {{
                        HttpURLConnection connection = null;

                        try {{
                            JSONObject payload = new JSONObject();
                            if (userId != null && !userId.trim().isEmpty()) {{
                                payload.put("user_id", userId);
                            }}
                            payload.put("platform", "android");
                            payload.put("fcm_token", token);
                            payload.put("package_name", context.getPackageName());
                            payload.put("app_version", BuildConfig.VERSION_NAME);
                            payload.put("device_model", Build.MANUFACTURER + " " + Build.MODEL);
                            payload.put("sdk_int", Build.VERSION.SDK_INT);

                            byte[] body = payload.toString().getBytes(StandardCharsets.UTF_8);

                            URL url = new URL(endpoint);
                            connection = (HttpURLConnection) url.openConnection();
                            connection.setRequestMethod("POST");
                            connection.setConnectTimeout(15000);
                            connection.setReadTimeout(15000);
                            connection.setDoOutput(true);
                            connection.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                            connection.setRequestProperty("Accept", "application/json");

                            if (authToken != null && !authToken.trim().isEmpty()) {{
                                connection.setRequestProperty("Authorization", "Bearer " + authToken.trim());
                            }}

                            if (!sessionCookies.isEmpty()) {{
                                connection.setRequestProperty("Cookie", sessionCookies);
                            }}

                            try (OutputStream outputStream = connection.getOutputStream()) {{
                                outputStream.write(body);
                            }}

                            int responseCode = connection.getResponseCode();

                            if (responseCode < 200 || responseCode >= 300) {{
                                System.out.println("Falha ao registrar token FCM. HTTP " + responseCode);
                            }}
                        }} catch (Exception exc) {{
                            System.out.println("Erro ao registrar token FCM: " + exc.getMessage());
                        }} finally {{
                            if (connection != null) {{
                                connection.disconnect();
                            }}
                        }}
                    }}).start();
                }}

                private static SharedPreferences prefs(Context context) {{
                    return context.getApplicationContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
                }}
            }}
            """,
        )

        write_file(
            java_dir / "MyFirebaseMessagingService.java",
            f"""
            package {package};

            import android.app.Notification;
            import android.app.NotificationChannel;
            import android.app.NotificationManager;
            import android.app.PendingIntent;
            import android.content.Context;
            import android.content.Intent;
            import android.os.Build;

            import com.google.firebase.messaging.FirebaseMessagingService;
            import com.google.firebase.messaging.RemoteMessage;

            import java.util.Map;

            public class MyFirebaseMessagingService extends FirebaseMessagingService {{
                private static final String CHANNEL_ID = "pirecal_portaria";
                private static final String CHANNEL_NAME = "Portaria Digital";

                @Override
                public void onNewToken(String token) {{
                    super.onNewToken(token);
                    PushRegistrar.saveToken(getApplicationContext(), token);
                    PushRegistrar.tryRegister(getApplicationContext());
                }}

                @Override
                public void onMessageReceived(RemoteMessage remoteMessage) {{
                    super.onMessageReceived(remoteMessage);

                    String title = null;
                    String body = null;
                    Map<String, String> data = remoteMessage.getData();

                    if (remoteMessage.getNotification() != null) {{
                        title = remoteMessage.getNotification().getTitle();
                        body = remoteMessage.getNotification().getBody();
                    }}

                    if ((title == null || title.trim().isEmpty()) && data != null) {{
                        title = data.get("title");
                    }}

                    if ((body == null || body.trim().isEmpty()) && data != null) {{
                        body = data.get("body");
                    }}

                    if (title == null || title.trim().isEmpty()) {{
                        title = "Pirecal Agendamento";
                    }}

                    if (body == null || body.trim().isEmpty()) {{
                        body = "Você possui uma nova notificação.";
                    }}

                    showNotification(title, body);
                }}

                private void showNotification(String title, String body) {{
                    NotificationManager notificationManager =
                        (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);

                    if (notificationManager == null) {{
                        return;
                    }}

                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {{
                        NotificationChannel channel = new NotificationChannel(
                            CHANNEL_ID,
                            CHANNEL_NAME,
                            NotificationManager.IMPORTANCE_DEFAULT
                        );

                        notificationManager.createNotificationChannel(channel);
                    }}

                    Intent intent = new Intent(this, MainActivity.class);
                    intent.setAction("OPEN_NOTIFICATION");
                    intent.addFlags(
                        Intent.FLAG_ACTIVITY_CLEAR_TOP |
                        Intent.FLAG_ACTIVITY_SINGLE_TOP
                    );

                    int requestCode = (int) System.currentTimeMillis();

                    int flags = PendingIntent.FLAG_UPDATE_CURRENT;

                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {{
                        flags |= PendingIntent.FLAG_IMMUTABLE;
                    }}

                    PendingIntent pendingIntent = PendingIntent.getActivity(
                        this,
                        requestCode,
                        intent,
                        flags
                    );

                    Notification.Builder builder = Build.VERSION.SDK_INT >= Build.VERSION_CODES.O
                        ? new Notification.Builder(this, CHANNEL_ID)
                        : new Notification.Builder(this);

                    Notification notification = builder
                        .setSmallIcon(getApplicationInfo().icon)
                        .setContentTitle(title)
                        .setContentText(body)
                        .setStyle(new Notification.BigTextStyle().bigText(body))
                        .setAutoCancel(true)
                        .setContentIntent(pendingIntent)
                        .build();

                    notificationManager.notify(
                        (int) System.currentTimeMillis(),
                        notification
                    );
                }}
            }}
            """,
        )

    print(f"\nProjeto Android criado em: {project_dir}")

    if enable_splash:
        print("Splash animada habilitada com fundo branco e escala responsiva para celular/tablet.")

    if enable_fcm:
        print("Firebase Messaging habilitado.")
        print("Ponte WebView disponível: window.AndroidBridge.registerLoggedUser(userId)")
        print("Token atual: window.AndroidBridge.getFcmToken()")

    return project_dir


def build_android_apk(project_dir: Path, gradle_version: str):
    gradlew_name = "gradlew.bat" if platform.system().lower().startswith("win") else "gradlew"
    gradlew = project_dir / gradlew_name

    if not gradlew.exists():
        gradle = shutil.which("gradle")
        if not gradle:
            raise SystemExit(
                "Gradle não encontrado no PATH. Instale o Gradle ou gere o projeto "
                "e abra no Android Studio."
            )

        run([gradle, "wrapper", "--gradle-version", gradle_version], project_dir)

    if not platform.system().lower().startswith("win"):
        gradlew.chmod(gradlew.stat().st_mode | stat.S_IEXEC)

    run([str(gradlew), ":app:clean", ":app:assembleDebug"], project_dir)

    apk_dir = project_dir / "app" / "build" / "outputs" / "apk" / "debug"
    apks = list(apk_dir.glob("*.apk"))

    if not apks:
        raise SystemExit("Build finalizado, mas nenhum APK foi encontrado.")

    print("\nAPK gerado:")
    for apk in apks:
        print(f" - {apk.resolve()}")

def build_android_aab(project_dir: Path, gradle_version: str):
    keystore_properties = project_dir / "keystore.properties"

    if not keystore_properties.exists():
        raise SystemExit(
            "Arquivo keystore.properties não encontrado na raiz do projeto Android.\n"
            f"Crie o arquivo em: {keystore_properties}\n"
            "Sem ele, o AAB release não será assinado corretamente."
        )

    gradlew_name = "gradlew.bat" if platform.system().lower().startswith("win") else "gradlew"
    gradlew = project_dir / gradlew_name

    if not gradlew.exists():
        gradle = shutil.which("gradle")

        if not gradle:
            raise SystemExit(
                "Gradle não encontrado no PATH. Instale o Gradle ou gere o projeto "
                "e abra no Android Studio."
            )

        run([gradle, "wrapper", "--gradle-version", gradle_version], project_dir)

    if not platform.system().lower().startswith("win"):
        gradlew.chmod(gradlew.stat().st_mode | stat.S_IEXEC)

    run([str(gradlew), ":app:clean", ":app:bundleRelease"], project_dir)

    aab_dir = project_dir / "app" / "build" / "outputs" / "bundle" / "release"
    aabs = list(aab_dir.glob("*.aab"))

    if not aabs:
        raise SystemExit("Build finalizado, mas nenhum AAB release foi encontrado.")

    print("\nAAB release gerado:")
    for aab in aabs:
        print(f" - {aab.resolve()}")


def generate_ios_assets(sources_dir: Path, icon_path: str, splash_gif: str):
    icon_source = Path(icon_path).expanduser().resolve()
    splash_source = Path(splash_gif).expanduser().resolve()

    if not icon_source.exists():
        raise SystemExit(f"Icone iOS nao encontrado: {icon_source}")
    if not splash_source.exists():
        raise SystemExit(f"Splash iOS nao encontrado: {splash_source}")

    assets_dir = sources_dir / "Assets.xcassets"
    app_icon_dir = assets_dir / "AppIcon.appiconset"
    splash_dir = assets_dir / "SplashLaunch.imageset"

    icon = Image.open(icon_source).convert("RGBA")
    icon = ImageOps.fit(icon, (1024, 1024), method=Image.LANCZOS)
    flattened_icon = Image.new("RGBA", icon.size, (255, 255, 255, 255))
    flattened_icon.alpha_composite(icon)
    flattened_icon = flattened_icon.convert("RGB")

    icon_specs = [
        ("iphone", "20x20", "2x", 40),
        ("iphone", "20x20", "3x", 60),
        ("iphone", "29x29", "2x", 58),
        ("iphone", "29x29", "3x", 87),
        ("iphone", "40x40", "2x", 80),
        ("iphone", "40x40", "3x", 120),
        ("iphone", "60x60", "2x", 120),
        ("iphone", "60x60", "3x", 180),
        ("ipad", "20x20", "1x", 20),
        ("ipad", "20x20", "2x", 40),
        ("ipad", "29x29", "1x", 29),
        ("ipad", "29x29", "2x", 58),
        ("ipad", "40x40", "1x", 40),
        ("ipad", "40x40", "2x", 80),
        ("ipad", "76x76", "1x", 76),
        ("ipad", "76x76", "2x", 152),
        ("ipad", "83.5x83.5", "2x", 167),
        ("ios-marketing", "1024x1024", "1x", 1024),
    ]

    icon_images = []
    for idiom, size, scale, pixels in icon_specs:
        filename = f"icon-{idiom}-{size.replace('.', '_')}@{scale}.png"
        output = app_icon_dir / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        flattened_icon.resize((pixels, pixels), Image.LANCZOS).save(output, "PNG")
        icon_images.append(
            {"idiom": idiom, "size": size, "scale": scale, "filename": filename}
        )

    write_file(
        app_icon_dir / "Contents.json",
        json.dumps(
            {
                "images": icon_images,
                "info": {"author": "xcode", "version": 1},
            },
            indent=2,
        ),
    )

    splash = Image.open(splash_source)
    splash.seek(0)
    splash_frame = splash.convert("RGBA")
    background = Image.new("RGBA", splash_frame.size, (72, 124, 172, 255))
    background.alpha_composite(splash_frame)
    splash_frame = background.convert("RGB")

    splash_images = []
    for scale, dimensions in (("1x", (640, 360)), ("2x", (1280, 720)), ("3x", (1920, 1080))):
        filename = f"splash-launch@{scale}.png"
        output = splash_dir / filename
        output.parent.mkdir(parents=True, exist_ok=True)
        ImageOps.fit(splash_frame, dimensions, method=Image.LANCZOS).save(output, "PNG")
        splash_images.append(
            {"idiom": "universal", "scale": scale, "filename": filename}
        )

    write_file(
        splash_dir / "Contents.json",
        json.dumps(
            {
                "images": splash_images,
                "info": {"author": "xcode", "version": 1},
            },
            indent=2,
        ),
    )

    shutil.copy2(splash_source, sources_dir / "splash.gif")

    write_file(
        sources_dir / "LaunchScreen.storyboard",
        """
        <?xml version="1.0" encoding="UTF-8"?>
        <document type="com.apple.InterfaceBuilder3.CocoaTouch.Storyboard.XIB" version="3.0" toolsVersion="26000" targetRuntime="iOS.CocoaTouch" propertyAccessControl="none" useAutolayout="YES" launchScreen="YES" useTraitCollections="YES" initialViewController="launch-controller">
            <device id="retina6_12" orientation="portrait" appearance="light"/>
            <dependencies>
                <deployment identifier="iOS"/>
                <plugIn identifier="com.apple.InterfaceBuilder.IBCocoaTouchPlugin" version="26000"/>
                <capability name="Safe area layout guides" minToolsVersion="9.0"/>
            </dependencies>
            <scenes>
                <scene sceneID="launch-scene">
                    <objects>
                        <viewController id="launch-controller" sceneMemberID="viewController">
                            <view key="view" contentMode="scaleToFill" id="launch-view">
                                <rect key="frame" x="0.0" y="0.0" width="393" height="852"/>
                                <subviews>
                                    <imageView clipsSubviews="YES" userInteractionEnabled="NO" contentMode="scaleAspectFill" image="SplashLaunch" translatesAutoresizingMaskIntoConstraints="NO" id="launch-image">
                                        <rect key="frame" x="0.0" y="0.0" width="393" height="852"/>
                                    </imageView>
                                </subviews>
                                <viewLayoutGuide key="safeArea" id="launch-safe-area"/>
                                <color key="backgroundColor" red="0.2823529412" green="0.4862745098" blue="0.6745098039" alpha="1" colorSpace="custom" customColorSpace="sRGB"/>
                                <constraints>
                                    <constraint firstItem="launch-image" firstAttribute="leading" secondItem="launch-view" secondAttribute="leading" id="launch-leading"/>
                                    <constraint firstAttribute="trailing" secondItem="launch-image" secondAttribute="trailing" id="launch-trailing"/>
                                    <constraint firstItem="launch-image" firstAttribute="top" secondItem="launch-view" secondAttribute="top" id="launch-top"/>
                                    <constraint firstAttribute="bottom" secondItem="launch-image" secondAttribute="bottom" id="launch-bottom"/>
                                </constraints>
                            </view>
                        </viewController>
                        <placeholder placeholderIdentifier="IBFirstResponder" id="launch-responder" userLabel="First Responder" sceneMemberID="firstResponder"/>
                    </objects>
                    <point key="canvasLocation" x="53" y="375"/>
                </scene>
            </scenes>
            <resources>
                <image name="SplashLaunch" width="640" height="360"/>
            </resources>
        </document>
        """,
    )


def create_ios_project(
    out_dir: Path,
    url: str,
    app_name: str,
    bundle_id: str,
    version_code: int,
    version_name: str,
    icon_path: str,
    splash_gif: str,
    team_id: str = "",
):
    validate_package(bundle_id)
    validate_url(url)

    if version_code < 1:
        raise SystemExit("O version-code do iOS precisa ser maior que zero")
    if not re.fullmatch(r"\d+(\.\d+){0,2}", version_name):
        raise SystemExit("Versao iOS invalida. Use um formato como 1.0 ou 1.0.0")
    if team_id and not re.fullmatch(r"[A-Z0-9]{10}", team_id):
        raise SystemExit("Team ID invalido. Ele deve ter 10 letras/numeros")

    project_name = safe_project_name(app_name)
    project_dir = out_dir / f"{project_name}_ios"
    sources_dir = project_dir / "Sources"

    team_setting = f"\n              DEVELOPMENT_TEAM: {team_id}" if team_id else ""

    write_file(
        project_dir / "project.yml",
        f"""
        name: {project_name}
        options:
          deploymentTarget:
            iOS: "14.0"
        targets:
          {project_name}:
            type: application
            platform: iOS
            sources:
              - Sources
            settings:
              PRODUCT_BUNDLE_IDENTIFIER: {bundle_id}
              INFOPLIST_FILE: Sources/Info.plist
              GENERATE_INFOPLIST_FILE: NO
              ASSETCATALOG_COMPILER_APPICON_NAME: AppIcon
              TARGETED_DEVICE_FAMILY: "1,2"
              SWIFT_VERSION: "5.0"
              CODE_SIGN_STYLE: Automatic{team_setting}
        """,
    )

    allow_http = "http://" in url.lower()

    ats_config = """
            <key>NSAppTransportSecurity</key>
            <dict>
                <key>NSAllowsArbitraryLoads</key>
                <true/>
            </dict>
    """ if allow_http else ""

    write_file(
        sources_dir / "Info.plist",
        f"""
        <?xml version="1.0" encoding="UTF-8"?>
        <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
        "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
        <plist version="1.0">
        <dict>
            <key>CFBundleDisplayName</key>
            <string>{html.escape(app_name)}</string>
            <key>CFBundleExecutable</key>
            <string>$(EXECUTABLE_NAME)</string>
            <key>CFBundleIdentifier</key>
            <string>$(PRODUCT_BUNDLE_IDENTIFIER)</string>
            <key>CFBundleInfoDictionaryVersion</key>
            <string>6.0</string>
            <key>CFBundleName</key>
            <string>$(PRODUCT_NAME)</string>
            <key>CFBundlePackageType</key>
            <string>APPL</string>
            <key>CFBundleVersion</key>
            <string>{version_code}</string>
            <key>CFBundleShortVersionString</key>
            <string>{version_name}</string>
            <key>ITSAppUsesNonExemptEncryption</key>
            <false/>
            <key>LSRequiresIPhoneOS</key>
            <true/>
            <key>UILaunchStoryboardName</key>
            <string>LaunchScreen</string>
            <key>UISupportedInterfaceOrientations</key>
            <array>
                <string>UIInterfaceOrientationPortrait</string>
            </array>
            <key>UISupportedInterfaceOrientations~ipad</key>
            <array>
                <string>UIInterfaceOrientationPortrait</string>
                <string>UIInterfaceOrientationPortraitUpsideDown</string>
            </array>
            {ats_config}
        </dict>
        </plist>
        """,
    )

    write_file(
        sources_dir / "AppDelegate.swift",
        """
        import UIKit

        @main
        class AppDelegate: UIResponder, UIApplicationDelegate {
            var window: UIWindow?

            func application(
                _ application: UIApplication,
                didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
            ) -> Bool {
                window = UIWindow(frame: UIScreen.main.bounds)
                window?.rootViewController = ViewController()
                window?.makeKeyAndVisible()
                return true
            }
        }
        """,
    )

    view_controller = """
    import UIKit
    import WebKit

    class ViewController: UIViewController, WKNavigationDelegate {
        private let homeURL = URL(string: __URL__)!
        private var webView: WKWebView!
        private let progressView = UIProgressView(progressViewStyle: .default)
            private var splashView: WKWebView?
            private var splashStartedAt = Date()

        override func viewDidLoad() {
            super.viewDidLoad()

            view.backgroundColor = UIColor(red: 0.0, green: 0.141, blue: 0.345, alpha: 1.0)

            let config = WKWebViewConfiguration()
            config.allowsInlineMediaPlayback = true

            webView = WKWebView(frame: .zero, configuration: config)
            webView.navigationDelegate = self
            webView.translatesAutoresizingMaskIntoConstraints = false

            progressView.translatesAutoresizingMaskIntoConstraints = false
            progressView.progress = 0

            view.addSubview(webView)
            view.addSubview(progressView)

            NSLayoutConstraint.activate([
                webView.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
                webView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
                webView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
                webView.bottomAnchor.constraint(equalTo: view.bottomAnchor),

                progressView.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
                progressView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
                progressView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
                progressView.heightAnchor.constraint(equalToConstant: 3)
            ])

                showSplash()
            webView.addObserver(self, forKeyPath: "estimatedProgress", options: .new, context: nil)
            webView.load(URLRequest(url: homeURL))
        }

            private func showSplash() {
                guard let gifURL = Bundle.main.url(forResource: "splash", withExtension: "gif") else {
                    return
                }

                let splash = WKWebView(frame: .zero)
                splash.isOpaque = false
                splash.backgroundColor = UIColor(red: 72.0 / 255.0, green: 124.0 / 255.0, blue: 172.0 / 255.0, alpha: 1.0)
                splash.scrollView.isScrollEnabled = false
                splash.isUserInteractionEnabled = false
                splash.translatesAutoresizingMaskIntoConstraints = false

                let page = "<html><head><meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1'/><style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:#487cac}img{width:100%;height:100%;object-fit:cover}</style></head><body><img src='splash.gif'/></body></html>"
                splash.loadHTMLString(page, baseURL: gifURL.deletingLastPathComponent())
                view.addSubview(splash)

                NSLayoutConstraint.activate([
                    splash.topAnchor.constraint(equalTo: view.topAnchor),
                    splash.leadingAnchor.constraint(equalTo: view.leadingAnchor),
                    splash.trailingAnchor.constraint(equalTo: view.trailingAnchor),
                    splash.bottomAnchor.constraint(equalTo: view.bottomAnchor)
                ])

                splashView = splash
                splashStartedAt = Date()
                DispatchQueue.main.asyncAfter(deadline: .now() + 10.0) { [weak self] in
                    self?.hideSplash()
                }
            }

            private func hideSplash() {
                guard let splash = splashView else { return }
                let elapsed = Date().timeIntervalSince(splashStartedAt)
                let delay = max(0.0, 1.5 - elapsed)

                DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self, weak splash] in
                    guard let self = self, let splash = splash, self.splashView === splash else { return }
                    UIView.animate(withDuration: 0.25, animations: {
                        splash.alpha = 0
                    }, completion: { _ in
                        splash.removeFromSuperview()
                        self.splashView = nil
                    })
                }
            }

            func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
                if webView === self.webView {
                    hideSplash()
                }
            }

            func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
                hideSplash()
            }

            func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
                hideSplash()
            }

        override func observeValue(
            forKeyPath keyPath: String?,
            of object: Any?,
            change: [NSKeyValueChangeKey : Any]?,
            context: UnsafeMutableRawPointer?
        ) {
            if keyPath == "estimatedProgress" {
                progressView.progress = Float(webView.estimatedProgress)
                progressView.isHidden = webView.estimatedProgress >= 1.0
            }
        }

        deinit {
            webView?.removeObserver(self, forKeyPath: "estimatedProgress")
        }
    }
    """

    view_controller = textwrap.dedent(view_controller).replace("__URL__", json.dumps(url))
    write_file(sources_dir / "ViewController.swift", view_controller)

    generate_ios_assets(
        sources_dir=sources_dir,
        icon_path=icon_path,
        splash_gif=splash_gif,
    )

    print(f"\nProjeto iOS criado em: {project_dir}")
    print(f"Versao iOS: {version_name} ({version_code})")
    print("Icone, launch screen e splash animada incluidos.")
    print("Para gerar .xcodeproj no macOS, instale XcodeGen e rode:")
    print(f"  cd {project_dir}")
    print("  xcodegen")
    print("Depois abra o projeto no Xcode para assinar e gerar o IPA.")

    return project_dir


def generate_android_icons(project_dir: Path, icon_path: str):
    src = Path(icon_path)

    if not src.exists():
        raise SystemExit(f"Ícone não encontrado: {src}")

    img = Image.open(src).convert("RGBA")

    sizes = {
        "mipmap-mdpi": 48,
        "mipmap-hdpi": 72,
        "mipmap-xhdpi": 96,
        "mipmap-xxhdpi": 144,
        "mipmap-xxxhdpi": 192,
    }

    for folder, size in sizes.items():
        out_dir = project_dir / "app" / "src" / "main" / "res" / folder
        out_dir.mkdir(parents=True, exist_ok=True)

        resized = img.resize((size, size), Image.LANCZOS)
        resized.save(out_dir / "ic_launcher.png")
        resized.save(out_dir / "ic_launcher_round.png")

    adaptive_dir = project_dir / "app" / "src" / "main" / "res" / "mipmap-anydpi-v26"
    if adaptive_dir.exists():
        for file in ["ic_launcher.xml", "ic_launcher_round.xml"]:
            target = adaptive_dir / file
            if target.exists():
                target.unlink()

    print(f"Ícones Android gerados a partir de: {src}")


def main():
    parser = argparse.ArgumentParser(
        description="Gera app nativo WebView Android/iOS para uma URL publicada."
    )

    parser.add_argument("--url", required=True, help="URL do portal. Ex: https://agenda.seudominio.com")
    parser.add_argument("--name", required=True, help="Nome do aplicativo. Ex: Pirecal Agenda")
    parser.add_argument("--package", required=True, help="Package/bundle id. Ex: br.com.pirecal.agenda")
    parser.add_argument("--out", default="./saida_app", help="Pasta de saída")
    parser.add_argument("--platform", choices=["android", "ios", "both"], default="android")
    parser.add_argument("--build-apk", action="store_true", help="Gera APK debug automaticamente no Android")
    parser.add_argument("--build-aab", action="store_true", help="Gera AAB release assinado automaticamente no Android")
    parser.add_argument("--allow-http", action="store_true", help="Permite HTTP sem HTTPS no Android")
    parser.add_argument("--version-code", type=int, default=1)
    parser.add_argument("--version-name", default="1.0.0")
    parser.add_argument("--team-id", default="", help="Apple Developer Team ID para assinatura iOS")
    parser.add_argument("--agp-version", default=DEFAULT_AGP_VERSION)
    parser.add_argument("--gradle-version", default=DEFAULT_GRADLE_VERSION)
    parser.add_argument("--compile-sdk", type=int, default=DEFAULT_COMPILE_SDK)
    parser.add_argument("--min-sdk", type=int, default=DEFAULT_MIN_SDK)
    parser.add_argument("--target-sdk", type=int, default=DEFAULT_TARGET_SDK)
    parser.add_argument("--icon", help="Caminho do ícone PNG quadrado. Ex: C:\\icones\\pirecal.png")
    parser.add_argument(
        "--splash-gif",
        help=(
            "Caminho do GIF da splash. O gerador recorta automaticamente "
            "as margens transparentes e centraliza em fundo branco."
        ),
    )

    parser.add_argument("--firebase-json", help="Caminho para o google-services.json. Se informado, habilita Firebase Messaging no Android.")
    parser.add_argument("--push-register-url", default="", help="Endpoint do seu backend para registrar user_id + token FCM.")
    parser.add_argument("--firebase-bom-version", default=DEFAULT_FIREBASE_BOM_VERSION)
    parser.add_argument("--google-services-version", default=DEFAULT_GOOGLE_SERVICES_VERSION)

    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    android_project = None

    if args.platform in ("android", "both"):
        android_project = create_android_project(
            out_dir=out_dir,
            url=args.url,
            app_name=args.name,
            package=args.package,
            version_code=args.version_code,
            version_name=args.version_name,
            allow_http=args.allow_http,
            agp_version=args.agp_version,
            compile_sdk=args.compile_sdk,
            min_sdk=args.min_sdk,
            target_sdk=args.target_sdk,
            firebase_json=args.firebase_json,
            push_register_url=args.push_register_url,
            firebase_bom_version=args.firebase_bom_version,
            google_services_version=args.google_services_version,
            splash_gif=args.splash_gif,
        )

        if args.icon:
            generate_android_icons(android_project, args.icon)

        if args.build_apk:
            build_android_apk(android_project, args.gradle_version)

        if args.build_aab:
            build_android_aab(android_project, args.gradle_version)

    if args.platform in ("ios", "both"):
        if not args.icon:
            raise SystemExit("Informe --icon para gerar o aplicativo iOS")
        if not args.splash_gif:
            raise SystemExit("Informe --splash-gif para gerar o aplicativo iOS")

        create_ios_project(
            out_dir=out_dir,
            url=args.url,
            app_name=args.name,
            bundle_id=args.package,
            version_code=args.version_code,
            version_name=args.version_name,
            icon_path=args.icon,
            splash_gif=args.splash_gif,
            team_id=args.team_id,
        )


if __name__ == "__main__":
    main()


# Exemplo Android - DEBUG:
# python gerar_webview_app_com_splash_v4.py --url "http://192.168.1.51:8080" --name "Pirecal Agendamento" --package "br.com.pirecal.agendamento" --version-name "1.0.78" --platform android --build-apk --icon "C:\\xampp\\htdocs\\htdocs\\carregamento\\assets\\version 2.ico" --firebase-json "C:\\Android\\google-services.json" --push-register-url "http://192.168.1.51:8080/api/register_device.php" --splash-gif "C:\\Android\\PORTARIA\\logo.gif"

# Exemplo Android - AAB:
#python gerar_webview_app_com_splash.py --url "https://mobile.pirecal.com.br:8697" --name "Portaria Digital Pirecal" --package "br.com.pirecal.portaria" --version-code 1 --version-name "1.0" --platform android --build-aab --icon "C:\\Android\\PORTARIA\\ICONE-COLORFUL-APPMOBILE.png" --firebase-json "C:\\Android\\PORTARIA\\google-services.json" --push-register-url "https://mobile.pirecal.com.br:8697/api/register_device.php" --splash-gif "C:\\Android\\PORTARIA\\logo.gif"

#python gerar_webview_app_com_splash.py --url "https://mobile.pirecal.com.br:8697" --name "Portaria Digital Pirecal" --package "br.com.pirecal.portaria" --version-code 1 --version-name "1.0" --platform android --build-apk --icon "C:\\Android\\PORTARIA\\ICONE-COLORFUL-APPMOBILE.png" --firebase-json "C:\\Android\\PORTARIA\\google-services.json" --push-register-url "https://mobile.pirecal.com.br:8697/api/register_device.php" --splash-gif "C:\\Android\\PORTARIA\\logo.gif"
