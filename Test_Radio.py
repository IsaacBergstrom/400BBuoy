from controller_esp32 import ESP32Config
from sx127x import SX127x
from lora_config import LORA_CONFIG

device_config = ESP32Config(
    sck=LORA_CONFIG['sck'],
    mosi=LORA_CONFIG['mosi'],
    miso=LORA_CONFIG['miso'],
    ss=LORA_CONFIG['cs'],      # 'cs' in your config is 'ss' in the driver
    reset=LORA_CONFIG['rst'],
    dio0=LORA_CONFIG['dio0']
)

# 2. Setup the Radio Parameters
# The driver expects 'tx_power_level', 'signal_bandwidth', etc.
lora_parameters = {
    'frequency': LORA_CONFIG['frequency'],
    'tx_power_level': LORA_CONFIG['tx_power'],
    'signal_bandwidth': LORA_CONFIG['bandwidth'],
    'spreading_factor': LORA_CONFIG['sf'],
    'coding_rate': LORA_CONFIG['coding_rate'],
    'preamble_length': LORA_CONFIG['preamble'],
    'sync_word': LORA_CONFIG['sync_word'],
    'enable_CRC': LORA_CONFIG['crc']
}

# 3. Initialize
lora = SX127x(device_config, parameters=lora_parameters)