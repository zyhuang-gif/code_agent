from normalizer import normalize_name


def make_username(first, last):
    return f"{normalize_name(first)}.{normalize_name(last)}"
