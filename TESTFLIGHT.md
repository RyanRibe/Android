# Publicacao do Portaria Digital Pirecal no TestFlight

Este repositorio gera e envia o aplicativo iOS pelo workflow
`Publicar iOS no TestFlight`.

## Identidade do aplicativo

- Nome: `Portaria Digital Pirecal`
- URL: `https://mobile.pirecal.com.br:8703/`
- Bundle ID: `br.com.pirecal.portaria`
- Apple Team ID: `28Z29WK4CZ`

## 1. Criar o aplicativo no App Store Connect

Em **App Store Connect > Apps**, crie um novo app para iOS usando o Bundle ID
`br.com.pirecal.portaria`. O registro do app precisa existir antes do primeiro
envio ao TestFlight.

## 2. Criar uma chave da API

Em **App Store Connect > Users and Access > Integrations**, clique em **API do
App Store Connect** no menu esquerdo. Nao use a opcao **Segredo compartilhado**,
pois ela pertence a compras dentro do app.

Se aparecer **Solicitar acesso**, o Account Holder precisa liberar primeiro o
acesso da equipe a API. Depois, em **Chaves da equipe**, clique no botao `+`,
informe um nome como `GitHub Actions` e selecione o papel **Gerente de apps**
(`App Manager` na interface em ingles). Gere a chave e baixe o arquivo
`AuthKey_XXXXXXXXXX.p8`. A Apple permite baixar esse arquivo somente uma vez.

Anote o **Issuer ID** e o **Key ID**.

## 3. Criar o certificado Apple Distribution

Crie um certificado do tipo **Apple Distribution** em **Certificates,
Identifiers & Profiles**. O certificado e sua chave privada devem ser
exportados juntos para um arquivo `.p12` protegido por senha.

No Windows, o OpenSSL incluído no Git for Windows pode ser usado para criar a
chave e o CSR. Faça isso fora do repositorio:

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

Envie o arquivo `.certSigningRequest` ao portal da Apple e baixe o certificado
como `distribution.cer`. Em seguida, gere o `.p12`:

```powershell
& $openssl x509 -inform DER -in distribution.cer -out AppleDistribution.pem
& $openssl pkcs12 -export `
  -inkey AppleDistribution.key `
  -in AppleDistribution.pem `
  -out AppleDistribution.p12 `
  -name "Apple Distribution"
```

Guarde a senha informada no ultimo comando. Nunca coloque `.key`, `.p8` ou
`.p12` dentro deste repositorio.

## 4. Criar o provisioning profile

Em **Certificates, Identifiers & Profiles > Profiles**, crie um profile do tipo
**App Store Connect** para o App ID `br.com.pirecal.portaria`, usando o
certificado Apple Distribution criado acima. O workflow baixa esse profile
automaticamente.

## 5. Configurar o GitHub

Em **Settings > Secrets and variables > Actions**, crie estas **Variables**:

- `APPSTORE_ISSUER_ID`: Issuer ID da chave da API.
- `APPSTORE_API_KEY_ID`: Key ID da chave da API.

Crie estes **Secrets**:

- `APPSTORE_API_PRIVATE_KEY`: conteudo completo do arquivo `.p8`.
- `APPSTORE_CERTIFICATES_FILE_BASE64`: arquivo `.p12` convertido para Base64.
- `APPSTORE_CERTIFICATES_PASSWORD`: senha usada na exportacao do `.p12`.

Para copiar os valores no Windows:

```powershell
Get-Content -Raw "$env:USERPROFILE\Downloads\AuthKey_XXXXXXXXXX.p8" | Set-Clipboard

[Convert]::ToBase64String(
  [IO.File]::ReadAllBytes("$env:USERPROFILE\AppleSigning\AppleDistribution.p12")
) | Set-Clipboard
```

## 6. Executar

Depois de enviar os arquivos do repositorio ao GitHub, abra **Actions >
Publicar iOS no TestFlight > Run workflow**, informe a versao `1.0` e execute.

Quando a Apple terminar o processamento, abra a aba **TestFlight** no App Store
Connect, adicione o build a um grupo de testes internos e aceite o convite no
iPhone pelo aplicativo TestFlight.

O workflow encerra depois que o upload e aceito pela Apple. O processamento do
build continua em segundo plano e pode levar alguns minutos. Consulte a aba
**TestFlight** e o e-mail da conta para acompanhar a aprovacao tecnica do
binario.
