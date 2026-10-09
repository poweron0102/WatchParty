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

## Falhas temporárias de reprodução

Cada requisição remota tem até cinco tentativas, com esperas de 1, 2, 4 e 8 segundos
e orçamento de 30 segundos. `Retry-After` aceita segundos ou data HTTP. Respostas
420/429 impõem uma espera compartilhada por host; se a espera exceder o orçamento,
o worker retorna a indisponibilidade e o prazo restante sem fazer outra chamada.
O download por byte range só repete respostas incompletas ou ranges inválidos,
sem reiniciar uma sequência HTTP esgotada.

O protocolo JSON Lines continua na versão 1. Eventos `failed` podem incluir os
campos opcionais `stage`, `status`, `operation`, `attempt` e `retry_after` (segundos).
O servidor traduz a falha da origem em HTTP 503 com `Retry-After`. Os diagnósticos
identificam a etapa e o segmento; URLs assinadas e credenciais são removidas.
