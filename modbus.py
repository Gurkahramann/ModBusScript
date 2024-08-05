from threading import Thread
import serial
import time
from flask import Flask, jsonify
from pyModbusTCP.server import ModbusServer
from pyModbusTCP.client import ModbusClient
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
import signal
import sys
import os
import configparser

app = Flask(__name__)
modbus_ip = "0.0.0.0"
modbus_port = 502
current_value = None
running = True
ser = None
config_path = "C:/config.ini"  # İstenilen yola ayarlanabilir

def get_com_port():
    ip_address = get_local_ip()  # Lokal IP adresini al
    default_com_port = "COM1"
    config = configparser.ConfigParser()
    try:
        config.read(config_path)
        if config.has_section('COM_PORTS') and ip_address in config['COM_PORTS']:
            return config['COM_PORTS'][ip_address]
    except Exception as e:
        print(f"Config dosyası okunurken hata: {e}")
    return default_com_port

def get_local_ip():
    import socket
    return socket.gethostbyname(socket.gethostname())

# COM port ayarları
com_port = get_com_port()
baud_rate = 9600
timeout = 1

# Modbus veri bloklarını oluştur
store = ModbusSlaveContext(
    di=ModbusSequentialDataBlock(0, [0] * 100),
    co=ModbusSequentialDataBlock(0, [0] * 100),
    hr=ModbusSequentialDataBlock(0, [0] * 100),
    ir=ModbusSequentialDataBlock(0, [0] * 100)
)
context = ModbusServerContext(slaves=store, single=True)

identity = ModbusDeviceIdentification()
identity.VendorName = 'EZM-9920'
identity.ProductCode = '9920'
identity.ProductName = 'Test'
identity.ModelName = 'TestModel'
identity.MajorMinorRevision = '1.0'

def update_data_block(value):
    try:
        value_float = float(value)
        value_int = int(value_float * 100)  # Değeri integer olarak saklamak için ölçekleyin
        if value_float < 0:
            context[0].setValues(3, 0, [0])  # 1. adrese 0 yaz
            context[0].setValues(3, 1, [abs(value_int)])  # 2. adrese mutlak değeri yaz
        else:
            context[0].setValues(3, 0, [value_int])  # 1. adrese değeri yaz
            context[0].setValues(3, 1, [0])  # 2. adrese 0 yaz
    except Exception as e:
        print(f"Modbus Register Güncellenirken Hata: {e}")
        return None  # Hata durumunda None döndür

def send_command(ser, command):
    ser.write(command.encode())
    time.sleep(1)
    if ser.in_waiting > 0:
        data = ser.read(ser.in_waiting)
        try:
            value = data.decode('utf-8', errors='ignore').strip()
            value_float = update_data_block(value)
            if value_float is not None:
                return value_float
        except ValueError:
            print(f"Geçersiz veri alındı: {data}")
    else:
        print("Veri bekleniyor...")
    return None

def start_serial_communication():
    global running
    global ser
    global com_port  # com_port değişkenini global olarak tanımla
    attempts = 0
    max_attempts = 2
    while attempts < max_attempts:
        try:
            ser = serial.Serial(com_port, baud_rate, timeout=timeout, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, bytesize=serial.EIGHTBITS)
            print(f"{com_port} portu açıldı.")
            break
        except serial.SerialException as e:
            print(f"{com_port} portu açılırken hata: {e}")
            attempts += 1
            if attempts >= max_attempts:
                com_port = "COM1"  # Varsayılan COM1 portuna geç
                try:
                    ser = serial.Serial(com_port, baud_rate, timeout=timeout, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, bytesize=serial.EIGHTBITS)
                    print(f"{com_port} portu açıldı.")
                except serial.SerialException as e:
                    print(f"{com_port} portu açılırken hata: {e}")
                    ser = None
                    break

    if ser:
        try:
            while running:
                command = "P"  # Gönderilecek komut
                send_command(ser, command)
                # time.sleep(1)  # Bir süre bekleyin ve tekrar deneyin
        except KeyboardInterrupt:
            print("Çıkış yapılıyor...")
        finally:
            ser.close()
            print(f"{com_port} portu kapatıldı.")

def read_from_modbus_client():
    global running
    global current_value
    client = ModbusClient(host="localhost", port=502, auto_open=True)
    while running:
        if client.is_open:
            
            # Modbus'tan gelen veriyi oku
            regs = client.read_holding_registers(0, 2)  # 0 ve 1. adreslerdeki verileri oku

            if regs:
                if regs[1] == 82 and regs[0] != 0:  # ASCII value of 'R'
                    send_command(ser, "R")  # Reset komutu gönder
                    client.write_multiple_registers(0, [0, 0])  # Sıfırlama işlemi tamamlandıktan sonra 0 yaz
                else:
                    writeValue = context[0].getValues(3, 0, 2)  # 0 ve 1. adreslerdeki verileri al
                    # Modbus'taki değer ile güncellenmesi gereken değeri karşılaştır
                    if regs != writeValue:
                        client.write_multiple_registers(0, writeValue)  # Değerler farklıysa güncelle
                
                if regs[0] == 0:
                    value = -regs[1] / 100.0  # Negatif değeri geri dönüştür
                else:
                    value = regs[0] / 100.0  # Pozitif değeri geri dönüştür
                current_value = value
                print(f"Modbus'tan okunan değer: {value}")
        else:
            client.open()
        time.sleep(1)

@app.route('/reset', methods=['GET'])
def reset_counter():
    global context
    send_command(ser, "R")  # Sayaç sıfırlama komutu gönder
    return jsonify({'result': 'Sayaç sıfırlandı'})

def start_modbus_server():
    server = ModbusServer(host=modbus_ip, port=modbus_port, no_block=True)
    print("Modbus TCP sunucusu başlatılıyor...")
    server.start()

@app.route('/value', methods=['GET'])
def get_value():
    return jsonify({'value': current_value})

def signal_handler(sig, frame):
    global running
    running = False
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)

    # Modbus TCP sunucusunu ayrı bir thread'de başlat
    modbus_thread = Thread(target=start_modbus_server)
    modbus_thread.start()

    # Seri port iletişimini başlat
    serial_thread = Thread(target=start_serial_communication)
    serial_thread.start()

    # Modbus client iletişimini başlat
    modbus_client_thread = Thread(target=read_from_modbus_client)
    modbus_client_thread.start()

    app.run(host='0.0.0.0', port=5001)
