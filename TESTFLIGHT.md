# Gerar e publicar um WebView iOS no TestFlight

Este guia documenta o processo completo usado para gerar, assinar, enviar e testar o **Portaria Digital Pirecal** no TestFlight usando Windows, GitHub Actions e uma conta ativa do Apple Developer Program.

O fluxo pode ser reutilizado para outros aplicativos alterando o bloco `env:` no começo de `.github/workflows/testflight-ios.yml`, os arquivos de imagem/Firebase e, opcionalmente, o bloco de configuração no começo de `gerar_webview_app_com_splash.py`.

## Configuração atual

| Item | Valor |
| --- | --- |
| Nome | `Portaria Digital Pirecal` |
| URL | `https://mobile.pirecal.com.br:8703/` |
| Bundle ID | `br.com.pirecal.portaria` |
| SKU | `br.com.pirecal.portaria` |
| Apple Team ID | `28Z29WK4CZ` |
| App Store ID | `6819294303` |
| Versão | `1.0` |
| iOS mínimo | `15.0` |
| Firebase Apple SDK | `12.19.2` |
| Firebase App ID | `1:539812983799:ios:80f7871fa63db2d8cdb4f2` |

## Arquivos usados

- `.github/workflows/testflight-ios.yml`: gera, assina e envia o IPA.
- `gerar_webview_app_com_splash.py`: gera o projeto Xcode completo.
- `ICONE-COLORFUL-APPMOBILE.png`: ícone 1024 x 1024.
- `logo.gif`: splash animada.
- `GoogleService-Info.plist`: configuração pública do app Firebase iOS.
- `.gitignore`: permite somente o `GoogleService-Info.plist` entre arquivos `.plist`.

Nunca envie ao Git arquivos `.p8`, `.p12`, chaves privadas, senhas ou o JSON de uma conta de serviço Firebase Admin.

## 1. Preparar o repositório Git

```powershell
git config --global user.name "Ryan Ribeiro"
git config --global user.email "SEU_EMAIL"

cd C:\Android
git init
git branch -M main
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/RyanRibe/Android.git
git push -u origin main
```

Avisos sobre conversão de `LF` para `CRLF` no Windows não impedem o build.

## 2. Criar o App ID na Apple

Em **Apple Developer > Certificates, Identifiers & Profiles > Identifiers**:

1. Crie ou abra o identificador explícito `br.com.pirecal.portaria`.
2. Ative a capability **Push Notifications**.
3. Salve as alterações.

Ao adaptar para outro app, use exatamente o mesmo Bundle ID no Apple Developer, App Store Connect, Firebase, workflow e Python.

## 3. Criar o app no App Store Connect

Em **App Store Connect > Apps**, crie um aplicativo iOS com nome `Portaria Digital Pirecal`, Bundle ID `br.com.pirecal.portaria` e SKU `br.com.pirecal.portaria`.

O registro precisa existir antes do primeiro upload. O App Store Connect associa o binário usando Bundle ID, versão e número da compilação.

## 4. Criar a chave da API do App Store Connect

Abra **Usuários e acesso > Integrações > API do App Store Connect**. Não use **Segredo compartilhado**, que pertence a compras dentro do app.

Em **Chaves da equipe**:

1. Clique em `+` e use um nome como `GitHub Actions`.
2. Selecione **Gerente de apps** (`App Manager`).
3. Gere e baixe `AuthKey_XXXXXXXXXX.p8`.
4. Anote o **Issuer ID** e o **Key ID**.

A Apple permite baixar esse `.p8` apenas uma vez.

## 5. Criar o certificado Apple Distribution no Windows

```powershell
$openssl = "C:\Program Files\Git\usr\bin\openssl.exe"
$signingDir = Join-Path $env:USERPROFILE "AppleSigning"
New-Item -ItemType Directory -Force -Path $signingDir | Out-Null
Set-Location $signingDir

& $openssl genrsa -out AppleDistribution.key 2048
& $openssl req -new -key AppleDistribution.key `
  -out CertificateSigningRequest.certSigningRequest `
  -subj "/emailAddress=SEU_EMAIL/CN=Ryan Ribeiro/C=BR"
```

No Apple Developer, crie um certificado **Apple Distribution** com o CSR e baixe `distribution.cer`. Depois:

```powershell
& $openssl x509 -inform DER -in distribution.cer -out AppleDistribution.pem
& $openssl pkcs12 -export `
  -inkey AppleDistribution.key `
  -in AppleDistribution.pem `
  -out AppleDistribution.p12 `
  -name "Apple Distribution"
```

Guarde a senha definida no último comando.

## 6. Criar o provisioning profile

Depois de ativar **Push Notifications** no identificador, crie novamente um profile do tipo **App Store Connect** para `br.com.pirecal.portaria`, usando o certificado Apple Distribution.

É necessário recriar o profile após ativar Push Notifications. Um profile antigo não contém `aps-environment` e fará a assinatura falhar. O workflow baixa automaticamente o profile mais recente e confirma Team ID e Bundle ID.

## 7. Configurar o Firebase para iOS

No Firebase Console:

1. Registre o app Apple com Bundle ID `br.com.pirecal.portaria`.
2. Informe o Apple Team ID `28Z29WK4CZ`.
3. Informe o App Store ID `6819294303`.
4. Baixe `GoogleService-Info.plist` e coloque-o na raiz do repositório.

O `GoogleService-Info.plist` é configuração de cliente, não uma chave privada. O gerador valida seu Bundle ID.

### Ligar Firebase Cloud Messaging ao APNs

1. Em **Apple Developer > Keys**, crie uma chave com **Apple Push Notifications service (APNs)**.
2. Baixe a chave APNs `.p8` e anote o Key ID.
3. No Firebase Console, abra **Configurações do projeto > Cloud Messaging > Configuração do app Apple**.
4. Envie a chave APNs `.p8` com seu Key ID e Team ID `28Z29WK4CZ`.

Sem essa ligação, o app pode gerar um token FCM, mas o Firebase não conseguirá entregar notificações ao iPhone.

O projeto usa `FirebaseAnalyticsCore` sem IDFA e `FirebaseMessaging`. Ele solicita alerta, som e badge, registra no APNs e envia o token FCM com `platform: ios` para `https://mobile.pirecal.com.br:8703/api/register_device.php`, usando os cookies autenticados da WebView.

## 8. Configurar o GitHub

Em **Settings > Secrets and variables > Actions**, crie as variables:

- `APPSTORE_ISSUER_ID`: Issuer ID da API;
- `APPSTORE_API_KEY_ID`: Key ID da API.

Crie os secrets:

- `APPSTORE_API_PRIVATE_KEY`: conteúdo completo do `.p8` do App Store Connect;
- `APPSTORE_CERTIFICATES_FILE_BASE64`: conteúdo Base64 do `.p12`;
- `APPSTORE_CERTIFICATES_PASSWORD`: senha do `.p12`.

```powershell
Get-Content -Raw "$env:USERPROFILE\Downloads\AuthKey_XXXXXXXXXX.p8" | Set-Clipboard

[Convert]::ToBase64String(
  [IO.File]::ReadAllBytes("$env:USERPROFILE\AppleSigning\AppleDistribution.p12")
) | Set-Clipboard
```

## 9. Configuração reutilizável

No começo de `.github/workflows/testflight-ios.yml`, altere somente o bloco `env:` para outro aplicativo:

- `APP_NAME`, `APP_URL`, `BUNDLE_ID`, `APPLE_TEAM_ID`;
- `GENERATOR_SCRIPT`, `ICON_PATH`, `SPLASH_PATH`;
- `FIREBASE_PLIST_PATH`, `PUSH_REGISTER_URL`;
- `IOS_DEPLOYMENT_TARGET`, `IOS_FIREBASE_SDK_VERSION`;
- `IOS_SYSTEM_BAR_COLOR`, `IOS_SPLASH_BACKGROUND_COLOR`;
- `IOS_CAMERA_USAGE_DESCRIPTION`, `IOS_PHOTO_LIBRARY_USAGE_DESCRIPTION`;
- `ARCHIVE_NAME` e `ARTIFACT_PREFIX`.

O começo de `gerar_webview_app_com_splash.py` contém os mesmos padrões. Argumentos do YAML têm prioridade. O número do build usa `GITHUB_RUN_NUMBER`; a versão visível é informada em **Run workflow**.

## 10. Enviar e executar

Antes do próximo build, conclua o passo 6 para o profile incluir Push Notifications.

```powershell
cd C:\Android
git add .github/workflows/testflight-ios.yml `
        .gitignore `
        gerar_webview_app_com_splash.py `
        GoogleService-Info.plist `
        TESTFLIGHT.md
git commit -m "Melhora app iOS e adiciona Firebase Messaging"
git push origin main
```

Depois abra **GitHub > Actions > Publicar iOS no TestFlight > Run workflow**, informe a versão e execute.

O fluxo instala XcodeGen e Transporter, resolve Firebase via Swift Package Manager, gera o projeto, importa o certificado, baixa e valida o profile, cria o archive, exporta/preserva o IPA e envia ao TestFlight.

A assinatura manual fica configurada somente no alvo principal do aplicativo. O workflow fornece o nome do provisioning profile pela variável de compilação `APP_PROVISIONING_PROFILE`; assim, o profile da Portaria não é aplicado aos pacotes Swift do Firebase.

O job usa `wait-for-processing: false`: verde confirma que a Apple recebeu o IPA. O processamento continua em segundo plano. Não execute novamente apenas porque o build ainda não apareceu.

## 11. Testar no iPhone

1. Aguarde o build em **App Store Connect > TestFlight**.
2. Responda às perguntas de conformidade, se solicitadas.
3. Crie um grupo de testes internos e adicione o Apple ID.
4. No iPhone, instale TestFlight, aceite o convite e instale o app.
5. Aceite a permissão de notificações e faça login para associar o token à sessão.

Checklist:

- splash completa por aproximadamente 3,75 segundos, sem recorte e sobre fundo branco;
- conteúdo e tema da página ocupando também as áreas superior e inferior do iPhone;
- botão **Câmera** visível e abrindo a câmera traseira;
- uploads de foto e documentos funcionando;
- token com `platform = ios` em `user_push_tokens`;
- notificação recebida com app fechado, em segundo plano e aberto.

## 12. Correção do portal para câmera no iOS

O HTML já possuía `accept="image/*" capture="environment"`, mas o botão era mostrado apenas quando existia `AndroidBridge`.

Foi atualizado `\\172.31.200.67\dmz\Xampp\htdocs\PORTARIA_DIGITAL\includes\anexos.php`. Agora a detecção aceita Android, `window.PirecalApp` e iPhone/iPad. O app também declara `NSCameraUsageDescription` e `NSPhotoLibraryUsageDescription`. Como a pasta não possui Git, foi mantido `includes\anexos.php.bak-20261005-ios-camera`.

## 13. Splash e barras

O GIF possui 75 frames de 50 ms, totalizando 3.750 ms. A cor interna dos pixels transparentes do arquivo original é azul e alguns renderizadores podem exibi-la antes de aplicar a transparência. Agora o gerador achata todos os quadros diretamente sobre `IOS_SPLASH_BACKGROUND_COLOR` (branco neste app), eliminando essa passagem azul.

O gerador recorta as margens, usa `scaleAspectFit`/`contain` e respeita toda a animação. O Launch Screen passou a se chamar `LaunchScreenWhite`, evitando reutilizar a antiga tela azul armazenada pelo iOS. Ao testar essa alteração pela primeira vez, remova do iPhone a versão anterior antes de instalar o novo build para limpar o cache visual do sistema.

A WebView ocupa a tela de ponta a ponta, sem faixas nativas coloridas. O portal já usa `viewport-fit=cover` e `env(safe-area-inset-*)`, portanto os controles continuam fora do recorte e do indicador inferior. O app observa o `<meta name="theme-color">`: quando `theme.js` troca entre `#075d2b` e `#0a1220`, o fundo sob as áreas do sistema e o contraste dos ícones são atualizados. `IOS_SYSTEM_BAR_COLOR` é apenas a cor de fallback antes de a página carregar.

Se outro portal precisar controlar explicitamente o contraste, também pode chamar:

```javascript
window.PirecalApp?.setSystemBars({ color: '#0a1220', style: 'light' });
window.PirecalApp?.setSystemBars({ color: '#ffffff', style: 'dark' });
```

### Validação de formulários no iPhone

O balão padrão de campos `required` do WKWebView pode aparecer sob a câmera/notch quando a página ocupa a tela inteira. O app iOS intercepta apenas o evento HTML `invalid`, suprime esse balão e apresenta um aviso vermelho abaixo de `safe-area-inset-top`. O primeiro campo inválido recebe destaque, é centralizado com rolagem suave e ganha foco; depois que o valor se torna válido, o destaque e o aviso desaparecem. Esse comportamento é injetado somente no WKWebView e não altera o Android ou o acesso pelo navegador.

### Limites de zoom no iPhone

O app inicia a viewport na escala `1` e mantém `minimum-scale=1`, impedindo que a página seja reduzida para menos de 100% ou fique menor que a tela. A pinça continua habilitada para ampliar o conteúdo, até `maximum-scale=5`, e permite retornar à escala original. A rolagem e os controles continuam funcionando normalmente. Esses limites existem somente no app iOS.

## 14. Problemas encontrados

### `scanner: mapping values are not allowed in this context`

Era indentação inválida no YAML gerado. O `project.yml` agora é montado com indentação determinística.

### VS Code pede `user.name` e `user.email`

Configure a identidade Git conforme o passo 1.

### Workflow esperava o build e terminava em erro

O upload havia terminado, mas a API continuava consultando sua visibilidade. Foi adotado Apple Transporter e `wait-for-processing: false`.

### `ITMS-90474: Invalid bundle`

O app suportava iPad sem todas as orientações exigidas para multitarefa. O `Info.plist` agora declara as quatro orientações no iPad.

### Aviso `90068: Deployment target muito baixo`

O alvo foi atualizado de iOS 14.0 para 15.0, atendendo ao requisito anunciado pela Apple para abril de 2027 e ao mínimo do Firebase usado.

### Firebase informa que não aceita provisioning profile

Se o archive mostrar mensagens como `FirebaseMessaging does not support provisioning profiles`, confira se o comando `xcodebuild` não contém `PROVISIONING_PROFILE_SPECIFIER`, `CODE_SIGN_STYLE` ou `CODE_SIGN_IDENTITY` globais. Esses parâmetros seriam herdados por todas as dependências. Neste projeto, a configuração fica no alvo do app e o comando passa apenas `APP_PROVISIONING_PROFILE`, que é uma variável auxiliar usada por esse alvo.

### Build verde, mas ausente no TestFlight

Estas mensagens confirmam a entrega:

```text
Commit successful ... Portaria_Digital_Pirecal.ipa
1 package was uploaded successfully
Upload phase transition: UPLOADED -> COMPLETED
```

Aguarde o processamento e o e-mail da Apple. Se permanecer em `Processing` por mais de 24 horas, consulte **Build Uploads** e contate a Apple.

## 15. Privacidade

Antes da revisão pública, atualize **App Store Connect > Privacidade do app** para refletir o portal e Firebase Analytics/Messaging. `FirebaseAnalyticsCore` evita IDFA, mas ainda é necessário declarar corretamente diagnósticos, identificadores e notificações quando aplicável.
