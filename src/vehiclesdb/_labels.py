"""Display labels in English and Spanish: the canonical colour palette, kinds
and body types. The SAME strings as the JS SDK and the gem `vehicles` (0.9.2):
the slug is what you store, the label is what you show."""

LOCALES = ("en", "es")

# (slug, hex, {locale: name}) — frequency-ordered, as the gem's Colors::ALL.
COLORS = (
    ("white", "#F4F4F4", {"en": "White", "es": "Blanco"}),
    ("black", "#1B1B1B", {"en": "Black", "es": "Negro"}),
    ("grey", "#8A8D90", {"en": "Grey", "es": "Gris"}),
    ("silver", "#C7CCD1", {"en": "Silver", "es": "Plata"}),
    ("blue", "#27408B", {"en": "Blue", "es": "Azul"}),
    ("red", "#B81D24", {"en": "Red", "es": "Rojo"}),
    ("green", "#2E6B3E", {"en": "Green", "es": "Verde"}),
    ("brown", "#5A3A22", {"en": "Brown", "es": "Marrón"}),
    ("beige", "#D9C6A5", {"en": "Beige", "es": "Beige"}),
    ("orange", "#E8731A", {"en": "Orange", "es": "Naranja"}),
    ("yellow", "#F2C200", {"en": "Yellow", "es": "Amarillo"}),
    ("gold", "#C8A951", {"en": "Gold", "es": "Dorado"}),
    ("purple", "#6B3FA0", {"en": "Purple", "es": "Morado"}),
    ("other", "#9AA0A6", {"en": "Other", "es": "Otro"}),
)

# Normalized spellings that land on a palette slug. English ones mirror the
# gem's Colors::SYNONYMS; Spanish ones cover gender and common variants.
COLOR_SYNONYMS = {
    "gray": "grey", "silvery": "silver", "tan": "beige", "cream": "beige", "burgundy": "red", "navy": "blue",
    "blanca": "white", "negra": "black", "plateado": "silver", "plateada": "silver", "gris": "grey",
    "dorada": "gold", "amarilla": "yellow", "morada": "purple", "violeta": "purple", "granate": "red",
    "azul marino": "blue", "crema": "beige", "otra": "other",
}

KIND_LABELS = {
    "car": {"en": "Car", "es": "Coche"},
    "motorcycle": {"en": "Motorcycle", "es": "Moto"},
    "moped": {"en": "Moped", "es": "Ciclomotor"},
    "van": {"en": "Van", "es": "Furgoneta"},
    "truck": {"en": "Truck", "es": "Camión"},
    "bus": {"en": "Bus", "es": "Autobús"},
}

BODY_TYPE_LABELS = {
    "hatchback": {"en": "Hatchback", "es": "Compacto"},
    "sedan": {"en": "Sedan", "es": "Berlina"},
    "wagon": {"en": "Wagon", "es": "Familiar"},
    "suv": {"en": "SUV", "es": "SUV"},
    "mpv": {"en": "MPV", "es": "Monovolumen"},
    "coupe": {"en": "Coupe", "es": "Cupé"},
    "convertible": {"en": "Convertible", "es": "Descapotable"},
    "roadster": {"en": "Roadster", "es": "Roadster"},
    "pickup": {"en": "Pickup", "es": "Pick-up"},
    "van": {"en": "Van", "es": "Furgoneta"},
}


def locale_of(locale):
    """`es`, `es-ES`, `es_ES` -> `es`; anything unsupported -> `en`."""
    key = str(locale or "en").strip().lower().replace("_", "-").split("-")[0]
    return key if key in LOCALES else "en"
