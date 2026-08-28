# Crunchyroll worker

Worker privado do WatchParty para inspeção DASH e materialização segmentada. Ele é um
programa próprio: o downloader usado como referência de comportamento não é executado,
importado como pacote nem copiado para a build.

## Build para Windows

Requer Go 1.25 ou posterior. Na raiz do projeto:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File tools\crunchyroll-worker\build.ps1
```

O script testa o pacote e produz `bin\crunchyroll-worker.exe`. O executável é ignorado
pelo Git e deve permanecer local.

## Segredos

O cookie entra pelo `stdin` do processo, nunca na linha de comando. Configure os caminhos
somente no `save.json`. Para dispositivo bruto, use os dois campos:

```json
"client_id_path": "secrets\\client_id.bin",
"private_key_path": "secrets\\private_key.pem"
```

Como alternativa, remova esses campos e use apenas:

```json
"widevine_device_path": "secrets\\device.wvd"
```

Os caminhos relativos são resolvidos a partir da raiz em que o WatchParty é iniciado.
`*.bin`, `*.pem` e `*.wvd` estão ignorados pelo Git. Não coloque o conteúdo desses
arquivos nem o cookie em issues, logs ou commits.

O `stdout` é reservado ao protocolo JSON Lines. Tokens, licenças e chaves existem
somente na memória do worker; o cache recebe apenas artefatos derivados.
