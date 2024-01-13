# nvidia-endpoint-server
a test server for nvidia-smi to get values imported into homeassistant **USE ON OWN RISK**

start the server on your linux machine using your favorite techique then add this to config of HA

example on how to add to HA

```
sensor:
  - platform: rest
    resource: http://192.168.0.3:5000/powerusage
    name: GPU Power Usage
  - platform: rest
    resource: http://192.168.0.3:5000/temperature
    name: GPU Temperature
  - platform: rest
    resource: http://192.168.0.3:5000/fanspeed
    name: GPU Fan Speed
  - platform: rest
    resource: http://192.168.0.3:5000/memoryusage
    name: GPU Memory Usage
    resource: http://192.168.0.3:5000/gpuutil
    name: GPU utilization
