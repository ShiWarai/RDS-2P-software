#!/usr/bin/env python3
"""HTTP клиент для взаимодействия с CVC API сервером.

CVC (Command Voice Classifier) - классификатор голосовых команд на основе трансформеров.
"""

import requests
import time
from typing import Optional, Dict, List, Any
import logging

# Настройка логирования для ROS2
logger = logging.getLogger('rds_2p_commands.cvc_client')


class CVCClient:
    """HTTP клиент для CVC API сервера."""

    def __init__(self, base_url: str = "http://localhost:8000", timeout: float = 2.0):
        """
        Инициализация CVC клиента.

        Args:
            base_url: Базовый URL CVC сервера
            timeout: Таймаут для HTTP запросов в секундах
        """
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self._health_checked = False

    def check_health(self) -> bool:
        """
        Проверка доступности CVC сервера.

        Returns:
            True если сервер доступен, False иначе
        """
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=self.timeout
            )
            if response.status_code == 200:
                self._health_checked = True
                return True
        except Exception as e:
            logger.debug(f"CVC health check failed: {e}")
        return False

    def classify(
        self,
        text: str,
        return_confidence: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Классификация одного текста.

        Args:
            text: Текст команды для классификации
            return_confidence: Возвращать ли уровень уверенности

        Returns:
            Словарь с ключами 'command' и опционально 'confidence',
            или None в случае ошибки
        """
        try:
            response = requests.post(
                f"{self.base_url}/predict",
                json={
                    "text": text,
                    "return_confidence": return_confidence
                },
                timeout=self.timeout
            )
            response.raise_for_status()
            result = response.json()
            return result
        except requests.exceptions.RequestException as e:
            logger.warning(f"CVC classification failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during CVC classification: {e}")
            return None

    def classify_batch(
        self,
        texts: List[str],
        return_confidence: bool = True
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Batch классификация нескольких текстов.

        Args:
            texts: Список текстов команд для классификации
            return_confidence: Возвращать ли уровень уверенности

        Returns:
            Список словарей с результатами классификации,
            или None в случае ошибки
        """
        if not texts:
            return []

        try:
            response = requests.post(
                f"{self.base_url}/predict/batch",
                json={
                    "texts": texts,
                    "return_confidence": return_confidence
                },
                timeout=self.timeout * len(texts)  # Увеличиваем таймаут для batch
            )
            response.raise_for_status()
            result = response.json()
            return result
        except requests.exceptions.RequestException as e:
            logger.warning(f"CVC batch classification failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during CVC batch classification: {e}")
            return None

    def is_available(self) -> bool:
        """
        Проверка доступности сервера (с кэшированием результата).

        Returns:
            True если сервер доступен, False иначе
        """
        if not self._health_checked:
            return self.check_health()
        return True

