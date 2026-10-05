@echo off
setlocal

echo ============================================
echo Instalando ambiente Android sem Android Studio
echo ============================================

echo.
echo [1/5] Instalando JDK 17 via winget...
winget install -e --id EclipseAdoptium.Temurin.17.JDK

echo.
echo [2/5] Instalando Gradle manualmente...

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$version='9.3.1';" ^
 "$gradleRoot='C:\Gradle';" ^
 "$gradleHome=\"$gradleRoot\gradle-$version\";" ^
 "$zip=\"$env:TEMP\gradle-$version-bin.zip\";" ^
 "$url=\"https://services.gradle.org/distributions/gradle-$version-bin.zip\";" ^
 "New-Item -ItemType Directory -Force -Path $gradleRoot | Out-Null;" ^
 "Invoke-WebRequest $url -OutFile $zip;" ^
 "Expand-Archive $zip -DestinationPath $gradleRoot -Force;" ^
 "[Environment]::SetEnvironmentVariable('GRADLE_HOME', $gradleHome, 'User');" ^
 "$old=[Environment]::GetEnvironmentVariable('Path','User');" ^
 "$gradleBin=\"$gradleHome\bin\";" ^
 "if($old -notlike \"*$gradleBin*\"){ $old=$old+';'+$gradleBin };" ^
 "[Environment]::SetEnvironmentVariable('Path', $old, 'User');"

set GRADLE_HOME=C:\Gradle\gradle-9.3.1
set PATH=%PATH%;C:\Gradle\gradle-9.3.1\bin

echo.
echo [3/5] Baixando Android Command-Line Tools...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$sdk='C:\Android\Sdk';" ^
 "$zip=\"$env:TEMP\commandlinetools-win.zip\";" ^
 "$tmp=\"$env:TEMP\android_cmdline_tools\";" ^
 "New-Item -ItemType Directory -Force -Path $sdk | Out-Null;" ^
 "Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue;" ^
 "New-Item -ItemType Directory -Force -Path $tmp | Out-Null;" ^
 "Invoke-WebRequest 'https://dl.google.com/android/repository/commandlinetools-win-14742923_latest.zip' -OutFile $zip;" ^
 "Expand-Archive $zip -DestinationPath $tmp -Force;" ^
 "Remove-Item -Recurse -Force \"$sdk\cmdline-tools\latest\" -ErrorAction SilentlyContinue;" ^
 "New-Item -ItemType Directory -Force -Path \"$sdk\cmdline-tools\latest\" | Out-Null;" ^
 "Copy-Item \"$tmp\cmdline-tools\*\" \"$sdk\cmdline-tools\latest\" -Recurse -Force;"

echo.
echo [4/5] Configurando variaveis de ambiente...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
 "$sdk='C:\Android\Sdk';" ^
 "[Environment]::SetEnvironmentVariable('ANDROID_SDK_ROOT', $sdk, 'User');" ^
 "[Environment]::SetEnvironmentVariable('ANDROID_HOME', $sdk, 'User');" ^
 "$paths=@('$sdk\platform-tools','$sdk\cmdline-tools\latest\bin','$sdk\emulator');" ^
 "$old=[Environment]::GetEnvironmentVariable('Path','User');" ^
 "foreach($p in $paths){ if($old -notlike \"*$p*\"){ $old=$old+';'+$p } }" ^
 "[Environment]::SetEnvironmentVariable('Path', $old, 'User');"

set ANDROID_SDK_ROOT=C:\Android\Sdk
set ANDROID_HOME=C:\Android\Sdk
set PATH=%PATH%;C:\Android\Sdk\platform-tools;C:\Android\Sdk\cmdline-tools\latest\bin;C:\Android\Sdk\emulator

echo.
echo [5/5] Instalando pacotes Android SDK...
call C:\Android\Sdk\cmdline-tools\latest\bin\sdkmanager.bat --sdk_root=C:\Android\Sdk "platform-tools" "platforms;android-36" "build-tools;36.0.0" "cmdline-tools;latest"

echo.
echo Aceitando licencas Android SDK...
call C:\Android\Sdk\cmdline-tools\latest\bin\sdkmanager.bat --sdk_root=C:\Android\Sdk --licenses

echo.
echo ============================================
echo Ambiente instalado.
echo Feche e abra novamente o CMD ou VS Code.
echo ============================================

echo.
echo Testes recomendados:
echo java -version
echo gradle -v
echo sdkmanager --list
echo adb version

pause