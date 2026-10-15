def helper(sku):
    return normalize(sku)


def normalize(sku):
    return sku.strip().upper()
