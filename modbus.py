from threading import Thread
import serial
import time
from threading import Thread
from flask import Flask, jsonify
from pyModbusTCP.server import ModbusServer
from pyModbusTCP.client import ModbusClient
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.datastore import ModbusSequentialDataBlock, ModbusSlaveContext, ModbusServerContext
app = Flask(__name__)
modbus_ip = "0.0.0.0"
modbus_port = 502
current_value = None
# COM port ayarları
com_port = "COM5"
baud_rate = 9600
timeout = 1

# Modbus veri bloklarını oluştur
store = ModbusSlaveContext(
    di=ModbusSequentialDataBlock(0, [0]*100),
    co=ModbusSequentialDataBlock(0, [0]*100),
    hr=ModbusSequentialDataBlock(0, [0]*100),
    ir=ModbusSequentialDataBlock(0, [0]*100)
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
    time.sleep(0.5)
    if ser.in_waiting > 0:
        data = ser.read(ser.in_waiting)
        try:
            value = data.decode('utf-8', errors='ignore').strip()
            #print(f"Gelen Veri: {value}")
            update_data_block(value)
        except ValueError:
            print(f"Geçersiz veri alındı: {data}")
    else:
        print("Veri bekleniyor...")

def start_serial_communication():
    try:
        ser = serial.Serial(com_port, baud_rate, timeout=timeout, parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE, bytesize=serial.EIGHTBITS)
        print(f"{com_port} portu açıldı.")
    except serial.SerialException as e:
        print(f"{com_port} portu açılırken hata: {e}")
        ser = None

    if ser:
        try:
            while True:
                command = "P"  # Gönderilecek komut
                send_command(ser, command)
                #time.sleep(1)  # Bir süre bekleyin ve tekrar deneyin
        except KeyboardInterrupt:
            print("Çıkış yapılıyor...")
        finally:
            ser.close()
            print(f"{com_port} portu kapatıldı.")

def read_from_modbus_client():
    global current_value
    client = ModbusClient(host="localhost", port=502, auto_open=True)
    while True:
        if client.is_open:
            writeValue = context[0].getValues(3, 0, 2)  # 0 ve 1. adreslerdeki verileri al
            client.write_multiple_registers(0, writeValue)  # Bu verileri Modbus sunucusuna yaz
            regs = client.read_holding_registers(0, 2)  # 0 ve 1. adreslerdeki verileri oku
            if regs:
                if regs[0] == 0:
                    value = -regs[1] / 100.0  # Negatif değeri geri dönüştür
                else:
                    value = regs[0] / 100.0  # Pozitif değeri geri dönüştür
                current_value = value
                print(f"Modbus Client Okunan Veri: {value}")
            else:
                print("Modbus Client Veri Okuma Başarısız. Okunan Değer: None")
        else:
            print("Modbus Client Bağlanamadı. Tekrar Bağlanılıyor...")
            client.open()
        #time.sleep(2)


def start_modbus_server():
    server = ModbusServer(host=modbus_ip, port=modbus_port, no_block=True)
    print("Modbus TCP sunucusu başlatılıyor...")
    server.start()

@app.route('/value', methods=['GET'])
def get_value():
    return jsonify({'value': current_value})
if __name__ == "__main__":
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

    