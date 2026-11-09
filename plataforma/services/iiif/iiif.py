"""Piezas IIIF sin red: manifiesto (Presentation 3) e info.json (Image API 3, nivel 0)."""
from typing import Dict, List, Tuple

MINIATURA = 400  # ancho de la miniatura que se ofrece además del tamaño completo


def tamanos(ancho: int, alto: int) -> List[Dict[str, int]]:
    t = []
    if ancho > MINIATURA:
        t.append({"width": MINIATURA, "height": round(alto * MINIATURA / ancho)})
    t.append({"width": ancho, "height": alto})
    return t


def info_json(imagen_id: str, ancho: int, alto: int) -> dict:
    return {
        "@context": "http://iiif.io/api/image/3/context.json",
        "id": imagen_id,
        "type": "ImageService3",
        "protocol": "http://iiif.io/api/image",
        "profile": "level0",
        "width": ancho,
        "height": alto,
        "sizes": tamanos(ancho, alto),
    }


def manifiesto(base: str, tenant: str, signatura: str, dimensiones: List[Tuple[int, int]],
               ingestado_por: str) -> dict:
    """base = URL pública hasta /iiif/3 (incluido)."""
    raiz = f"{base}/{tenant}/{signatura}"
    lienzos = []
    for n, (w, h) in enumerate(dimensiones, start=1):
        img = f"{raiz}/{n}"
        lienzo = f"{raiz}/canvas/{n}"
        lienzos.append({
            "id": lienzo, "type": "Canvas", "label": {"es": [f"Imagen {n}"]}, "width": w, "height": h,
            "items": [{
                "id": f"{raiz}/page/{n}", "type": "AnnotationPage",
                "items": [{
                    "id": f"{raiz}/annotation/{n}", "type": "Annotation", "motivation": "painting", "target": lienzo,
                    "body": {"id": f"{img}/full/max/0/default.jpg", "type": "Image", "format": "image/jpeg",
                             "width": w, "height": h,
                             "service": [{"id": img, "type": "ImageService3", "profile": "level0"}]},
                }],
            }],
        })
    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": f"{raiz}/manifest",
        "type": "Manifest",
        "label": {"es": [f"Legajo {signatura}"]},
        "metadata": [
            {"label": {"es": ["Signatura"]}, "value": {"none": [signatura]}},
            {"label": {"es": ["Institución"]}, "value": {"none": [tenant]}},
            {"label": {"es": ["Ingresado por"]}, "value": {"none": [ingestado_por]}},
        ],
        "items": lienzos,
    }
