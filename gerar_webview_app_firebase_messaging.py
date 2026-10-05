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

from PIL import Image


DEFAULT_AGP_VERSION = "9.1.0"
DEFAULT_GRADLE_VERSION = "9.3.1"
DEFAULT_COMPILE_SDK = 36
DEFAULT_MIN_SDK = 23
DEFAULT_TARGET_SDK = 36
DEFAULT_FIREBASE_BOM_VERSION = "34.7.0"
DEFAULT_GOOGLE_SERVICES_VERSION = "4.4.4"


def write_file(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


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
):
    validate_package(package)
    parsed = validate_url(url)

    if parsed.scheme == "http":
        allow_http = True

    enable_fcm = bool(firebase_json)
    firebase_config_path = validate_firebase_json(firebase_json, package)

    project_name = safe_project_name(app_name)
    project_dir = out_dir / f"{project_name}_android"

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

    dependencies_block = f"""
            dependencies {{
            {androidx_core_dependency}
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
        """
        if enable_fcm else ""
    )

    fcm_java_imports = (
        """
    import android.Manifest;
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
        """
        if enable_fcm else ""
    )

    fcm_setup_calls = (
        """
            requestNotificationPermissionIfNeeded();
            installFirebaseMessagingBridge();
        """
        if enable_fcm else ""
    )

    fcm_java_methods = (
        """
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
        plugins {{
            id 'com.android.application'{google_services_app_plugin}
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
                    android:name=".MainActivity"
                    android:exported="true"
                    android:screenOrientation="portrait">
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
        """
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
__FCM_FIELDS__

        @SuppressLint("SetJavaScriptEnabled")
        @Override
        protected void onCreate(Bundle savedInstanceState) {
            super.onCreate(savedInstanceState);
            requestWindowFeature(Window.FEATURE_NO_TITLE);

            Window window = getWindow();

            window.setStatusBarColor(Color.parseColor("#002458"));
            window.setNavigationBarColor(Color.parseColor("#002458"));

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                window.setStatusBarContrastEnforced(false);
                window.setNavigationBarContrastEnforced(false);
            }

            window.getDecorView().setSystemUiVisibility(0);

            FrameLayout root = new FrameLayout(this);
            root.setBackgroundColor(Color.parseColor("#002458"));

            webView = new WebView(this);
            progressBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
            progressBar.setMax(100);
            progressBar.setProgress(0);

            root.addView(
                webView,
                new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT,
                    ViewGroup.LayoutParams.MATCH_PARENT
                )
            );

            FrameLayout.LayoutParams progressParams = new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT,
                8
            );
            root.addView(progressBar, progressParams);

            setContentView(root);

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

                @Override
                public void onReceivedError(
                    WebView view,
                    WebResourceRequest request,
                    WebResourceError error
                ) {
                    super.onReceivedError(view, request, error);

                    if (request != null && request.isForMainFrame()) {
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
                webView.loadUrl(HOME_URL);
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

__FCM_METHODS__
    }
    """

    main_activity = (
        textwrap.dedent(main_activity)
        .replace("__PACKAGE__", package)
        .replace("__URL__", json.dumps(url))
        .replace("__LOGOUT_URL__", json.dumps(f"{parsed.scheme}://{parsed.netloc}/logout.php"))
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

                    if (userId == null || userId.trim().isEmpty() || token == null || token.trim().isEmpty()) {{
                        return;
                    }}

                    new Thread(() -> {{
                        HttpURLConnection connection = null;

                        try {{
                            JSONObject payload = new JSONObject();
                            payload.put("user_id", userId);
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
                private static final String CHANNEL_ID = "pirecal_agendamentos";
                private static final String CHANNEL_NAME = "Agendamentos";

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
                    intent.addFlags(Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_SINGLE_TOP);

                    int flags = PendingIntent.FLAG_UPDATE_CURRENT;

                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {{
                        flags |= PendingIntent.FLAG_IMMUTABLE;
                    }}

                    PendingIntent pendingIntent = PendingIntent.getActivity(this, 0, intent, flags);

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

                    notificationManager.notify((int) System.currentTimeMillis(), notification);
                }}
            }}
            """,
        )

    print(f"\nProjeto Android criado em: {project_dir}")

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

    run([str(gradlew), ":app:assembleDebug"], project_dir)

    apk_dir = project_dir / "app" / "build" / "outputs" / "apk" / "debug"
    apks = list(apk_dir.glob("*.apk"))

    if not apks:
        raise SystemExit("Build finalizado, mas nenhum APK foi encontrado.")

    print("\nAPK gerado:")
    for apk in apks:
        print(f" - {apk.resolve()}")


def create_ios_project(out_dir: Path, url: str, app_name: str, bundle_id: str):
    validate_package(bundle_id)
    validate_url(url)

    project_name = safe_project_name(app_name)
    project_dir = out_dir / f"{project_name}_ios"
    sources_dir = project_dir / "Sources"

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
              TARGETED_DEVICE_FAMILY: "1,2"
              SWIFT_VERSION: "5.0"
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
            <key>CFBundleIdentifier</key>
            <string>$(PRODUCT_BUNDLE_IDENTIFIER)</string>
            <key>CFBundleVersion</key>
            <string>1</string>
            <key>CFBundleShortVersionString</key>
            <string>1.0.0</string>
            <key>UILaunchStoryboardName</key>
            <string>LaunchScreen</string>
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

            webView.addObserver(self, forKeyPath: "estimatedProgress", options: .new, context: nil)
            webView.load(URLRequest(url: homeURL))
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

    print(f"\nProjeto iOS base criado em: {project_dir}")
    print("Para push no iOS, configure Firebase iOS + APNs no Xcode.")
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
    parser.add_argument("--allow-http", action="store_true", help="Permite HTTP sem HTTPS no Android")
    parser.add_argument("--version-code", type=int, default=1)
    parser.add_argument("--version-name", default="1.0.0")
    parser.add_argument("--agp-version", default=DEFAULT_AGP_VERSION)
    parser.add_argument("--gradle-version", default=DEFAULT_GRADLE_VERSION)
    parser.add_argument("--compile-sdk", type=int, default=DEFAULT_COMPILE_SDK)
    parser.add_argument("--min-sdk", type=int, default=DEFAULT_MIN_SDK)
    parser.add_argument("--target-sdk", type=int, default=DEFAULT_TARGET_SDK)
    parser.add_argument("--icon", help="Caminho do ícone PNG quadrado. Ex: C:\\icones\\pirecal.png")

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
        )

        if args.icon:
            generate_android_icons(android_project, args.icon)

        if args.build_apk:
            build_android_apk(android_project, args.gradle_version)

    if args.platform in ("ios", "both"):
        create_ios_project(
            out_dir=out_dir,
            url=args.url,
            app_name=args.name,
            bundle_id=args.package,
        )


if __name__ == "__main__":
    main()


# Exemplo Android com FCM:
# python gerar_webview_app_firebase_messaging.py --url "http://192.168.1.51:8080" --name "Pirecal Agendamento" --package "br.com.pirecal.agendamento" --version-name "1.0.78" --platform android --build-apk --icon "C:\\xampp\\htdocs\\htdocs\\carregamento\\assets\\version 2.ico" --firebase-json "C:\\Android\\google-services.json" --push-register-url "http://192.168.1.51:8080/api/register_device.php"
