def slugify(s):
    return s.replace(" ", "-")


def truncate(s, n):
    return s[:n]


def parse_bool(s):
    return s == "true"