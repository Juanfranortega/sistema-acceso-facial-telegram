import logging
import os


os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
logging.getLogger("tensorflow").setLevel(logging.ERROR)


def verificar_rostro(imagen_referencia, imagen_recibida, modelo="SFace"):
    # La importación tardía permite que el bot y la página inicien rápido.
    from deepface import DeepFace

    resultado = DeepFace.verify(
        img1_path=str(imagen_referencia),
        img2_path=str(imagen_recibida),
        model_name=modelo,
        detector_backend="opencv",
        distance_metric="cosine",
        enforce_detection=True,
        align=True
    )

    return {
        "verificado": bool(resultado["verified"]),
        "distancia": float(resultado["distance"]),
        "umbral": float(resultado["threshold"])
    }
