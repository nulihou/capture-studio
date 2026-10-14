"""Possible chips by I2C address (v7).  Many parts share addresses: always shown as 'possible'."""
from __future__ import annotations

KNOWN = {
    0x10: ["IMX219/IMX477 摄像头 (MIPI)", "VEML7700 光照"], 0x1a: ["IMX219 摄像头 (MIPI)", "WM8960 音频编解码"],
    0x1d: ["ADXL345 加速度计", "LSM9DS0"], 0x1e: ["HMC5883L 磁力计"], 0x20: ["PCF8574/MCP23017 IO 扩展"],
    0x21: ["PCF8574/MCP23017 IO 扩展"], 0x23: ["BH1750 光照"], 0x27: ["PCF8574 LCD 背板"],
    0x29: ["VL53L0X 测距", "TSL2591 光照"], 0x36: ["OV5647 摄像头 (MIPI)", "MAX17048 电量计"],
    0x38: ["FT6x06 触摸", "AHT10/AHT20 温湿度"], 0x39: ["APDS-9960 手势/光照", "TSL2561 光照"],
    0x3c: ["SSD1306 OLED", "OV5640 摄像头 (MIPI)"], 0x3d: ["SSD1306 OLED"], 0x40: ["INA219/INA226 电流", "PCA9685 PWM", "HDC1080 温湿度"],
    0x41: ["INA219/INA226 电流"], 0x44: ["SHT3x 温湿度"], 0x45: ["SHT3x 温湿度"], 0x48: ["ADS1115 ADC", "TMP102 温度", "PCF8591 ADC"],
    0x49: ["ADS1115 ADC", "TMP102 温度"], 0x4a: ["ADS1115 ADC"], 0x4b: ["ADS1115 ADC"],
    0x50: ["24Cxx EEPROM", "显示器 EDID (DDC)"], 0x51: ["24Cxx EEPROM", "PCF8563 RTC"], 0x57: ["24C32 EEPROM (DS3231 模块)"],
    0x5a: ["MLX90614 红外测温", "CCS811 空气质量"], 0x5c: ["AM2320 温湿度"], 0x60: ["Si5351 时钟", "MPL3115A2 气压"],
    0x62: ["SCD40 CO₂"], 0x68: ["MPU6050/MPU9250 IMU", "DS3231/DS1307 RTC"], 0x69: ["MPU6050 IMU (AD0=1)"],
    0x6a: ["LSM6DS3 IMU"], 0x6b: ["LSM6DS3 IMU"], 0x70: ["TCA9548A I2C 多路复用"], 0x76: ["BME280/BMP280 温湿压"],
    0x77: ["BME280/BMP280/BMP180 温湿压"],
}


def hints(address: int) -> list[str]:
    return list(KNOWN.get(int(address), []))


def describe(address_text: str) -> str:
    """'0x68' or '0x1a (驱动占用)' -> '0x68 可能是 MPU6050/MPU9250 IMU / DS3231/DS1307 RTC'."""
    head = address_text.split()[0]
    try:
        value = int(head, 16)
    except ValueError:
        return address_text
    names = hints(value)
    return f"{address_text} 可能是 {' / '.join(names)}" if names else address_text
