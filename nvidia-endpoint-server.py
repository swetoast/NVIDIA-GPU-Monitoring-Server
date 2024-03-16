from flask import Flask, jsonify
import subprocess
import re
import configparser
import os

app = Flask('NVIDIA GPU Monitoring Server')

@app.route('/powerusage', methods=['GET'])
def get_power_usage():
    smi_output = subprocess.check_output(['nvidia-smi', '--query-gpu=power.draw', '--format=csv,noheader,nounits']).decode()
    power_usage = [float(re.search(r'\d+.\d+', line).group()) for line in smi_output.split('\n') if line.strip()]
    return jsonify({"power_usage": power_usage[0] if power_usage else None})

@app.route('/temperature', methods=['GET'])
def get_temperature():
    smi_output = subprocess.check_output(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits']).decode()
    temperature = [float(re.search(r'\d+', line).group()) for line in smi_output.split('\n') if line.strip()]
    return jsonify({"temperature": temperature[0] if temperature else None})

@app.route('/fanspeed', methods=['GET'])
def get_fan_speed():
    smi_output = subprocess.check_output(['nvidia-smi', '--query-gpu=fan.speed', '--format=csv,noheader,nounits']).decode()
    fan_speed = [float(re.search(r'\d+', line).group()) for line in smi_output.split('\n') if line.strip()]
    return jsonify({"fan_speed": fan_speed[0] if fan_speed else None})

@app.route('/memoryusage', methods=['GET'])
def get_memory_usage():
    smi_output = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits']).decode()
    memory_usage = [float(re.search(r'\d+', line).group()) for line in smi_output.split('\n') if line.strip()]
    return jsonify({"memory_usage": memory_usage[0] if memory_usage else None})

@app.route('/gpuutil', methods=['GET'])
def get_gpu_util():
    smi_output = subprocess.check_output(['nvidia-smi', '--query-gpu=utilization.gpu', '--format=csv,noheader,nounits']).decode()
    gpu_util = [float(re.search(r'\d+', line).group()) for line in smi_output.split('\n') if line.strip()]
    return jsonify({"gpu_util": gpu_util[0] if gpu_util else None})

@app.errorhandler(404)
def page_not_found(e):
    return """
<!DOCTYPE html>
<html>
<head>
    <style>
        body {font-family: Arial, sans-serif; margin: 0; padding: 0; background-color: #f0f0f0;}
        .container {width: 80%; margin: 20px auto; padding: 20px;}
        h1, h2 {color: #333;}
        ul {list-style: none; padding: 0;}
        li {margin: 10px 0; color: #333; background: #fff; padding: 10px; border-radius: 5px; box-shadow: 0 0 10px rgba(0,0,0,0.1);}
        a {color: #007BFF; text-decoration: none;}
        a:hover {color: #0056b3; text-decoration: underline;}
    </style>
</head>
<body>
    <div class="container">
        <h1>NVIDIA Server</h1>
        <ul>
            <li><a href='/powerusage'>Power Usage</a></li>
            <li><a href='/temperature'>Temperature</a></li>
            <li><a href='/fanspeed'>Fan Speed</a></li>
            <li><a href='/memoryusage'>Memory Usage</a></li>
            <li><a href='/gpuutil'>GPU Utilization</a></li>
        </ul>
    </div>
</body>
</html>
    """

if __name__ == '__main__':
    config = configparser.ConfigParser()
    dir_path = os.path.dirname(os.path.realpath(__file__))
    config_path = os.path.join(dir_path, 'nvidia-endpoint-server.conf')
    config.read(config_path)
    host = config.get('DEFAULT', 'HOST')
    port = config.getint('DEFAULT', 'PORT')
    use_https = config.getboolean('DEFAULT', 'USE_HTTPS')
    certificate_path = os.path.join(dir_path, config.get('DEFAULT', 'CERTIFICATE_PATH'))
    key_path = os.path.join(dir_path, config.get('DEFAULT', 'KEY_PATH'))

    if use_https:
        if os.path.exists(certificate_path) and os.path.exists(key_path):
            app.run(host=host, port=port, ssl_context=(certificate_path, key_path))
        else:
            print("Certificate or key not found. Running without SSL.")
            app.run(host=host, port=port)
    else:
        app.run(host=host, port=port)
