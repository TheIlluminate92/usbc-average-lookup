"""Desktop entry point. UI, database, and network services are separate modules."""

from usbc_average_lookup.database_app import AverageLookupApp, main

__all__ = ["AverageLookupApp", "main"]


if __name__ == "__main__":
    main()
