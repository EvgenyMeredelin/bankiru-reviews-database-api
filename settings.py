MPL_RUNTIME_CONFIG: dict[str, int | str] = {
    "figure.dpi" : 400,
    "font.family": "Arial"
}

DATABASE_PATH       : str = "bankiru_reviews.db"
DATETIME_DB_FORMAT  : str = "%Y-%m-%d %H:%M:%S"
DATETIME_PLOT_FORMAT: str = "%d.%m.%Y"
NO_RESULT_SENTINEL  : str = "Результат выполнения запроса пуст"
PLOT_MAX_ITEMS      : int = 3    # banks/products/locations
PLOT_TOP_N          : int = 5    # banks
PLOT_LABEL_MAXLEN   : int = 30   # characters
S3_URL_LIFESPAN     : int = 180  # seconds
