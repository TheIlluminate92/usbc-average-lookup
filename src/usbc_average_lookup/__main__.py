from multiprocessing import freeze_support

from usbc_average_lookup.app import main

if __name__ == "__main__":
    freeze_support()
    main()
