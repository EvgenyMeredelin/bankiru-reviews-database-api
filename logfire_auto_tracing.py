import logfire
import uvicorn
from decouple import config


logfire.configure(
    token=config("LOGFIRE_TOKEN"),
    code_source=logfire.CodeSource(
        repository="https://github.com/EvgenyMeredelin/bankiru-reviews-database-api",
        revision="main"
    )
)
logfire.install_auto_tracing(
    modules=["main", "tools", "uploaders"],
    min_duration=0
)


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config("VM_HOST"),
        port=int(config("VM_PORT")),
        reload=True
    )
