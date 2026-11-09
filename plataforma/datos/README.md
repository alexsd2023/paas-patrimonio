# Datos versionados (DVC)

`gt/` es el *ground truth* para entrenar y evaluar el HTR: cada línea de `gt/lineas.jsonl` dice de qué
documento es, qué número de línea, qué imagen la contiene y su transcripción revisada por una paleógrafa.

**La muestra que hay ahora es sintética** (35 líneas de protocolos notariales inventados) para que el
walking skeleton funcione de punta a punta. Se sustituye por el ground truth real (y sus imágenes
en `gt/<documento>/linea-NN.png`) sin cambiar nada más.

Git no guarda estos ficheros: guarda `gt.dvc`, que dice qué versión (md5) de la carpeta usa cada commit.
Los ficheros viven en el remoto de DVC (una carpeta en el servidor, por SSH).

    dvc add datos/gt            # tras cambiar los datos: nueva versión
    git add datos/gt.dvc        # y se fija en git
    dvc push                    # los ficheros, al servidor
    dvc pull                    # en otra máquina: trae la versión que dice gt.dvc
