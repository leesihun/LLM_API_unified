"""
Entry point for the streaming proxy agent.
"""
import uvicorn
from proxy_agent.config import PROXY_HOST, PROXY_PORT

if __name__ == "__main__":
    uvicorn.run("proxy_agent.main:app", host=PROXY_HOST, port=PROXY_PORT)
