#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import html
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import textwrap
from PIL import Image
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_AGP_VERSION = "9.1.0"
DEFAULT_GRADLE_VERSION = "9.3.1"
DEFAULT_COMPILE_SDK = 36
DEFAULT_MIN_SDK = 23
DEFAULT_TARGET_SDK = 36


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
        raise SystemExit(
            "Package inválido. Use algo como: br.com.suaempresa.agendamento"
        )


def safe_project_name(name: str):
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", name.strip())
    return value or "WebViewApp"


def package_to_path(package: str):
    return Path(*package.split("."))


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
):
    validate_package(package)
    parsed = validate_url(url)

    if parsed.scheme == "http":
        allow_http = True

    project_name = safe_project_name(app_name)
    project_dir = out_dir / f"{project_name}_android"

    android_cleartext = "true" if allow_http else "false"
    app_name_xml = html.escape(app_name, quote=True)
    java_dir = project_dir / "app" / "src" / "main" / "java" / package_to_path(package)

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
            id 'com.android.application' version '{agp_version}' apply false
        }}
        """,
    )

    write_file(
        project_dir / "gradle.properties",
        """
        org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
        android.useAndroidX=false
        android.nonTransitiveRClass=true
        """,
    )

    write_file(
        project_dir / "app" / "build.gradle",
        f"""
        plugins {{
            id 'com.android.application'
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

            compileOptions {{
                sourceCompatibility JavaVersion.VERSION_17
                targetCompatibility JavaVersion.VERSION_17
            }}
        }}
        """,
    )

    write_file(
        project_dir / "app" / "src" / "main" / "AndroidManifest.xml",
        f"""
        <manifest xmlns:android="http://schemas.android.com/apk/res/android">
            <uses-permission android:name="android.permission.INTERNET" />
            <uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />

            <application
                android:theme="@style/AppTheme"
                android:label="@string/app_name"
                android:icon="@mipmap/ic_launcher"
                android:roundIcon="@mipmap/ic_launcher_round"
                android:usesCleartextTraffic="{android_cleartext}"
                android:hardwareAccelerated="true"
                android:resizeableActivity="true"
                android:supportsRtl="true">

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
    import android.graphics.Color;
    import android.net.Uri;
    import android.os.Bundle;
    import android.os.Build;
    import android.os.Message;
    import android.view.View;
    import android.view.ViewGroup;
    import android.view.Window;
    import android.webkit.CookieManager;
    import android.webkit.DownloadListener;
    import android.webkit.WebChromeClient;
    import android.webkit.WebResourceRequest;
    import android.webkit.WebSettings;
    import android.webkit.WebView;
    import android.webkit.WebViewClient;
    import android.widget.FrameLayout;
    import android.widget.ProgressBar;
    

    public class MainActivity extends Activity {
        private static final String HOME_URL = __URL__;
        private WebView webView;
        private ProgressBar progressBar;

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
                    * Links target="_blank" serão tratados no WebChromeClient.onCreateWindow().
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
                webView.loadUrl(HOME_URL);
            }
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
    }
    """

    main_activity = (
        textwrap.dedent(main_activity)
        .replace("__PACKAGE__", package)
        .replace("__URL__", json.dumps(url))
    )

    write_file(java_dir / "MainActivity.java", main_activity)

    print(f"\nProjeto Android criado em: {project_dir}")
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

    # Remove o adaptive icon XML para o Android usar os PNGs gerados.
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


#python gerar_webview_app.py --url "http://10.0.70.192:8080" --name "Pirecal Agendamento" --package "br.com.pirecal.agendamento" --platform android --build-apk --icon "C:\Users\ryan.oliveira\Downloads\icon.png"
