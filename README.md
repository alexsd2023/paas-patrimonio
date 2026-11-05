# PaaS Patrimonio

Sitio estático con una pantalla de acceso y seis secciones:

- `/` Visión general para todos los públicos: la plataforma explicada como una ciudad, con zoom por capas y piezas
- `/simulador` Simulador de interacción por roles (instituciones, desarrolladores, participantes del Data Space, comunidades de origen)
- `/arquitectura` Arquitectura funcional de referencia
- `/nucleo` Núcleo de integración (backbone)
- `/backbone` Walking Skeleton: orden de montaje y flujo del test de extremo a extremo
- `/stack` Stack tecnológico por capas, con licencias y alternativas

## Acceso

Al entrar se muestra `/login`, con una ciudad que se construye mientras tanto. Usuario `admin`, contraseña `admin`.
Es una protección de demostración en el navegador (sessionStorage), **no un control de seguridad**: cualquiera puede leer el código.
Para proteger el sitio de verdad, activa la protección por contraseña de Vercel o pon el sitio detrás de un proveedor de identidad.

No necesita compilación: HTML, CSS y JavaScript sin dependencias.

## Probar en local

```bash
npx serve .
```

## Desplegar en Vercel

**Opción A: desde la terminal**

```bash
npm i -g vercel
vercel          # primer despliegue (vista previa)
vercel --prod   # producción
```

Si pregunta por el framework, elige **Other**, sin comando de build y con la raíz como directorio de salida.

**Opción B: desde GitHub**

1. Sube esta carpeta a un repositorio de GitHub.
2. En vercel.com: Add New → Project → importa el repositorio.
3. Framework Preset: **Other**. Build Command y Output Directory: vacíos.
4. Pulsa Deploy.

## Estructura

```
index.html         Visión general
simulador.html     Simulador
arquitectura.html  Arquitectura funcional
nucleo.html        Núcleo de integración (backbone)
backbone.html      Walking Skeleton
stack.html         Stack tecnológico
favicon.svg
vercel.json        URLs limpias y cabeceras de seguridad
```

Para editar o añadir escenarios del simulador, modifica el array `ROLES` en `simulador.html`. Para cambiar textos de la visión general, modifica el array `L` en `index.html`.
