import uvicorn
from .api import create_app
from .config import Settings

def main():
    settings=Settings.from_env();settings.validate_bind()
    uvicorn.run(create_app(settings),host=settings.host,port=settings.port,workers=1,access_log=True)

if __name__=='__main__':main()
