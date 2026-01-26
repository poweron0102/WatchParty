import asyncio
import logging

import aiohttp

from config import CF_API_TOKEN, CF_ZONE_ID, CF_RECORD_NAME, CF_PROXIED, CF_INTERVAL

# Configuração básica de log para ver o que está acontecendo
logging.basicConfig(level=logging.INFO, format='[DNS] %(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def get_public_ipv6():
    """Obtém o endereço IPv6 público atual usando a API do ipify."""
    try:
        async with aiohttp.ClientSession() as session:
            # Usamos api64 para garantir suporte a IPv6
            async with session.get('https://api64.ipify.org?format=json', timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('ip')
                else:
                    logger.error(f"Erro ao obter IP: Status {resp.status}")
                    return None
    except Exception as e:
        logger.error(f"Falha ao conectar serviço de IP: {e}")
        return None


async def update_cloudflare_record(session, current_ip):
    """Atualiza o registro AAAA na Cloudflare se o IP tiver mudado."""

    headers = {
        "Authorization": f"Bearer {CF_API_TOKEN}",
        "Content-Type": "application/json"
    }

    base_url = "https://api.cloudflare.com/client/v4"

    # 1. Obter o ID do registro DNS atual (precisamos do ID para atualizar)
    # Procuramos por um registro AAAA (IPv6) com o nome configurado
    search_url = f"{base_url}/zones/{CF_ZONE_ID}/dns_records?type=AAAA&name={CF_RECORD_NAME}"

    try:
        async with session.get(search_url, headers=headers) as resp:
            data = await resp.json()

            if not data.get('success'):
                logger.error(f"Erro ao buscar registro DNS: {data.get('errors')}")
                return

            records = data.get('result', [])
            if not records:
                logger.warning(
                    f"Nenhum registro AAAA encontrado para {CF_RECORD_NAME}. Crie-o manualmente primeiro.")
                return

            record = records[0]
            record_id = record['id']
            existing_ip = record['content']

            # 2. Verificar se precisa atualizar
            if existing_ip == current_ip:
                # logger.info("IP não mudou. Nenhuma ação necessária.")
                return

            logger.info(f"IP mudou de {existing_ip} para {current_ip}. Atualizando Cloudflare...")

            # 3. Atualizar o registro
            update_url = f"{base_url}/zones/{CF_ZONE_ID}/dns_records/{record_id}"
            payload = {
                "type": "AAAA",
                "name": CF_RECORD_NAME,
                "content": current_ip,
                "proxied": CF_PROXIED
            }

            async with session.put(update_url, headers=headers, json=payload) as update_resp:
                update_data = await update_resp.json()
                if update_data.get('success'):
                    logger.info(f"Sucesso! DNS atualizado para {current_ip}")
                else:
                    logger.error(f"Falha ao atualizar DNS: {update_data.get('errors')}")

    except Exception as e:
        logger.error(f"Erro na comunicação com a Cloudflare: {e}")


async def start_dns_updater():
    """
    Função principal loop que verifica e atualiza o DNS periodicamente.
    Deve ser iniciada como uma Task no asyncio.
    """
    if not CF_API_TOKEN or not CF_ZONE_ID:
        logger.warning("Configurações da Cloudflare incompletas. O atualizador de DNS não será iniciado.")
        return

    logger.info(f"Iniciando monitoramento de DNS para {CF_RECORD_NAME} (Intervalo: {CF_INTERVAL}s)")

    async with aiohttp.ClientSession() as session:
        while True:
            current_ipv6 = await get_public_ipv6()

            if current_ipv6:
                # Verifica se é um IPv6 válido (simples verificação de :)
                if ":" in current_ipv6:
                    await update_cloudflare_record(session, current_ipv6)
                else:
                    logger.warning(f"IP obtido não parece ser IPv6: {current_ipv6}")

            await asyncio.sleep(CF_INTERVAL)