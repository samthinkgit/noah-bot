# Noah Bot

Noah es un bot de Discord diseñado para el servidor **Chill de Cojines**, con funcionalidades como:
- Waifuracer (timers, leaderboards, rankings)
- Reacciones personalizadas por usuario
- Comandos de IA (preguntas, resúmenes, ayuda)
- Personalidad propia 😈🖤

Este proyecto utiliza **uv** para la gestión del entorno y dependencias.

---

## 🧩 Requisitos

- Python **3.10 o superior**
- Tener instalado **uv**

Si no tienes `uv`, instálalo siguiendo la guía oficial:  
👉 https://docs.astral.sh/uv/

---

## 📦 Instalación

1. Clona el repositorio:

```bash
git clone <url-del-repo>
cd noah-bot
````

2. Sincroniza el entorno y las dependencias con `uv`:

```bash
uv sync
```

Esto creará automáticamente el entorno virtual y descargará las dependencias necesarias usando `uv.lock`.

---

## 🔐 Variables de entorno

Debes crear un fichero **`.env`** en la raíz del proyecto con el token de Discord.

### 📄 `.env`

```env
DISCORD_BOT_TOKEN="YourBotToken"
```

---

## ▶️ Ejecutar el bot

Una vez instalado todo y creado el `.env`, ejecuta el bot con:

```bash
uv run noah-bot
```

Si todo está correcto, deberías ver algo como:

```
Bot connected as Noah
```
