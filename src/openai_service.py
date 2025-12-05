import json
import logging
from typing import Any, Dict

from openai import OpenAI

logger = logging.getLogger(__name__)


class OfferInterpreter:
    def __init__(self, api_key: str, model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model

    async def interpret(self, text: str) -> Dict[str, Any]:
        system_prompt = (
            "Ты ассистент CRM агрегатора платежей.\n"
            "Пользователь может:\n"
            "1) прислать ОФФЕР (описание платёжного канала или мерчанта);\n"
            "2) задать ПОИСКОВЫЙ ЗАПРОС по базе офферов простыми словами.\n\n"
            "Твоя задача — определить режим и вернуть ТОЛЬКО валидный JSON.\n"
            "Никакого текста кроме JSON.\n\n"
            "Правила классификации:\n"
            "- 'search' если пользователь просит показать, найти, выдать, дай, нужны и т.п.\n"
            "- 'offer' если перечислены условия конкретного канала/мерчанта (комиссия, курс, лимиты и т.д.).\n"
            "- Если сомневаешься — выбери 'offer' и сохрани весь текст в 'conditions'.\n\n"
            "Парсинг оффера:\n"
            "- Извлеки country, method, fee, rate, limits, kind (channel/merchant), fee_percent.\n"
            "- Всё, что не удалось разложить по полям, обязательно помести в 'conditions' (комментарии).\n"
            "- 'short_summary' — одно предложение о сути оффера.\n\n"
            "Парсинг поиска:\n"
            "- Понимай проценты: 'дешевле 11%' => max_fee_percent = 11.0.\n"
            "- Учитывай любые указания по стране/методу/статусу/kind.\n"
            "- Если явного запроса нет, но текст похож на оффер — верни 'offer'.\n"
        )

        response = self.client.chat.completions.create(
            model=self.model,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text},
            ],
        )

        content = response.choices[0].message.content
        logger.info("OpenAI response: %s", content)

        try:
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError("JSON is not an object")
            return parsed
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Не удалось распарсить JSON OpenAI: {exc}\nОтвет: {content}"
            ) from exc
