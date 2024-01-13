from flask import Flask, jsonify
import subprocess
import re

app = Flask('nvidia endpoint server')

@app.route('/powerusage', methods=['GET'])
def get_power_usage():
    smi_output = subprocess.check_output(['nvidia-smi', '--query-gpu=power.draw', '--format=csv,noheader,nounits']).decode()
    power_usage = [float(re.search(r'\d+.\d+', line).group()) for line in smi_output.split('\n') if line.strip()]
    return jsonify(power_usage)

@app.route('/temperature', methods=['GET'])
def get_temperature():
    smi_output = subprocess.check_output(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits']).decode()
    temperature = [float(re.search(r'\d+', line).group()) for line in smi_output.split('\n') if line.strip()]
    return jsonify(temperature)

@app.route('/fanspeed', methods=['GET'])
def get_fan_speed():
    smi_output = subprocess.check_output(['nvidia-smi', '--query-gpu=fan.speed', '--format=csv,noheader,nounits']).decode()
    fan_speed = [float(re.search(r'\d+', line).group()) for line in smi_output.split('\n') if line.strip()]
    return jsonify(fan_speed)

@app.route('/memoryusage', methods=['GET'])
def get_memory_usage():
    smi_output = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits']).decode()
    memory_usage = [float(re.search(r'\d+', line).group()) for line in smi_output.split('\n') if line.strip()]
    return jsonify(memory_usage)

if __name__ == '__main__':
    print("Server is starting...")
    print("Available endpoints:")
    print("1. /powerusage: Get the power usage of the GPU")
    print("2. /temperature: Get the temperature of the GPU")
    print("3. /fanspeed: Get the fan speed of the GPU")
    print("4. /memoryusage: Get the memory usage of the GPU")
    app.run(host='0.0.0.0', port=5000)
