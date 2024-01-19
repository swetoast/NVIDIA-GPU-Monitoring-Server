from flask import Flask, jsonify
import subprocess
import re
import configparser
import os

app = Flask('NVIDIA GPU Monitoring Server')

def query_gpu(query: str):
    try:
        smi_output = subprocess.check_output(['nvidia-smi', '--query-gpu=' + query, '--format=csv,noheader,nounits']).decode()
        result = [float(re.search(r'\d+.\d+', line).group()) for line in smi_output.split('\n') if line.strip()]
        return result[0] if result else None
    except Exception as e:
        return str(e)

@app.route('/powerusage', methods=['GET'])
def get_power_usage():
    return jsonify({"power_usage": query_gpu('power.draw')})

@app.route('/temperature', methods=['GET'])
def get_temperature():
    return jsonify({"temperature": query_gpu('temperature.gpu')})

@app.route('/fanspeed', methods=['GET'])
def get_fan_speed():
    return jsonify({"fan_speed": query_gpu('fan.speed')})

@app.route('/memoryusage', methods=['GET'])
def get_memory_usage():
    return jsonify({"memory_usage": query_gpu('memory.used')})

@app.route('/gpuutil', methods=['GET'])
def get_gpu_util():
    return jsonify({"gpu_util": query_gpu('utilization.gpu')})

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
