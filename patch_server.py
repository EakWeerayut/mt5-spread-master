import json

with open('server.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    new_lines.append(line)
    if 'if path == "/api/oil_chart_data":' in line:
        new_lines.extend([
            '        if path == "/api/tfx_chart_data":\n',
            '            try:\n',
            '                data = tfx_data_manager.get_chart_data()\n',
            '                self.send_response(200)\n',
            '                self.send_header("Content-Type", "application/json")\n',
            '                self.end_headers()\n',
            '                self.wfile.write(json.dumps(data).encode("utf-8"))\n',
            '            except Exception as e:\n',
            '                self.send_response(500)\n',
            '                self.send_header("Content-Type", "application/json")\n',
            '                self.end_headers()\n',
            '                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))\n',
            '            return\n\n'
        ])
    if 'if path == "/api/oil_fetch":' in line:
        new_lines.extend([
            '        if path == "/api/tfx_fetch":\n',
            '            try:\n',
            '                tfx_data_manager.fetch_new_data()\n',
            '                self.send_response(200)\n',
            '                self.send_header("Content-Type", "application/json")\n',
            '                self.end_headers()\n',
            '                self.wfile.write(json.dumps({"status": "success"}).encode("utf-8"))\n',
            '            except Exception as e:\n',
            '                self.send_response(500)\n',
            '                self.send_header("Content-Type", "application/json")\n',
            '                self.end_headers()\n',
            '                self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))\n',
            '            return\n\n'
        ])

with open('server.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)
