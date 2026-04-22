import sys
import os

def application(environ, start_response):
    status = "200 OK"
    response_headers = [("Content-type", "text/plain; charset=utf-8")]
    start_response(status, response_headers)
    
    msg = (
        "Hello from Passenger WSGI Test\n"
        f"Python: {sys.version}\n"
        "If you can see this, Passenger is working, and the issue is an OOM or Segfault in the main app."
    )
    return [msg.encode("utf-8")]
