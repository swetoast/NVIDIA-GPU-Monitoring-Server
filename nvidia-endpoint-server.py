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

@app.route('/gpuutil', methods=['GET'])
def get_gpu_util():
    smi_output = subprocess.check_output(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits']).decode()
    gpu_util = [float(re.search(r'\d+', line).group()) for line in smi_output.split('\n') if line.strip()]
    return jsonify(gpu_util)

@app.errorhandler(404)
def page_not_found(e):
    return """
<!DOCTYPE html>
<html>
<head>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f0f0f0;
        }
        .container {
            width: 80%;
            margin: 0 auto;
            padding: 20px;
        }
        h1 {
            color: #333;
        }
        h2 {
            color: #666;
        }
        ul {
            list-style-type: none;
            padding: 0;
        }
        li {
            margin: 10px 0;
            color: #333;
            background-color: #fff;
            padding: 10px;
            border-radius: 5px;
            box-shadow: 0px 0px 10px rgba(0,0,0,0.1);
        }
        a {
            color: #007BFF;
            text-decoration: none;
        }
        a:hover {
            color: #0056b3;
            text-decoration: underline;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>NVIDIA Endpoint Server</h1>
        <h2>Available Endpoints:</h2>
        <ul>
            <li><a href='/powerusage'>/powerusage: Get the power usage of the GPU</a></li>
            <li><a href='/temperature'>/temperature: Get the temperature of the GPU</a></li>
            <li><a href='/fanspeed'>/fanspeed: Get the fan speed of the GPU</a></li>
            <li><a href='/memoryusage'>/memoryusage: Get the memory usage of the GPU</a></li>
            <li><a href='/gpuutil'>/gpuutil: Get the GPU utilization</a></li>
        </ul>
    </div>
</body>
</html>
    """

if __name__ == '__main__':
    print("Server is starting...")
    print("Available endpoints:")
    print("1. /powerusage: Get the power usage of the GPU")
    print("2. /temperature: Get the temperature of the GPU")
    print("3. /fanspeed: Get the fan speed of the GPU")
    print("4. /memoryusage: Get the memory usage of the GPU")
    print("5. /gpuutil: Get the GPU utilization")
    app.run(host='0.0.0.0', port=5000)
