# Журнал сборок Alembic для кейса (C2–C5)

## polyBERT: `polyBERT-fac250`
- Источник: `https://huggingface.co/xushijie/polyBERT`, неофициальная копия весов. Официальный репозиторий закрыт (код по запросу, Academic Research Use License без права распространения), официальная модель на HF снята. **Образ держим только локально, в хаб не грузим.**
- Модель сборки: `openrouter/z-ai/glm-5.3`. Подсказка: грузить веса через sentence-transformers, четыре инструмента, примеры PS, BR, NR.
- Итог: 4 инструмента, 4 passed, 4 perfect; 11/11 тестов, 9/9 вызовов. Сборка с первого прохода, около 40 минут.
- Инструменты: `embed_psmiles`, `embed_blend`, `cosine_similarity`, `embed_table`.
- Адрес: `http://localhost:22012/mcp`, образ `alembic-tool:polyBERT-fac250`.
- **Внешняя проверка.** `embed_blend` для PS 25 % и BD 75 % вернул `[0.192369, 0.310134, -0.380432, …]`. У Наргизы вручную: `[0.19236892, 0.3101338, -0.38043225, …]`. Совпадение до шестого знака.
- Особенность: входом был репозиторий модели на HuggingFace без Python-пакета и без git-lfs весов после клона. Alembic собрал окружение и кэшировал веса на этапе Environment.

## PolymerGNN: `PolymerGNN-3b749e`
- Источник: `https://github.com/owencqueen/PolymerGNN`, лицензии нет, последний коммит в мае 2023.
- Модель сборки: `openrouter/z-ai/glm-5.2` (старт до переключения `.env`).
- Итог: 4 инструмента, 4 perfect; 8/8 тестов, 9/9 вызовов. Загружен в хаб.
- Инструменты: `train_joint_cv`, `predict_polymer_properties`, `get_composition_embedding`, `list_dataset_monomers`.

## mordred-community: `mordred-community-10e89b`
- Источник: `https://github.com/JacksonBurns/mordred-community`, BSD-3.
- Итог: 5 инструментов, 5 perfect; 15/15 тестов, 24/24 вызова. Загружен в хаб.

## Wan et al. 2024: `rubber-mechanical-properties-prediction-1c872d`
- Источник: `https://github.com/Vanguer/rubber-mechanical-properties-prediction`, лицензии нет. Репозиторий нашла сама система CoScientist в ходе прогона `tyre-main-2`; сборку запустил агент по запросу пользователя во втором ходе сессии.
- Итог: 4 инструмента, 4 perfect; 12/12 тестов, 8/8 вызовов. Загружен в хаб.
- Инструменты: `predict_strength`, `predict_elongation`, `predict_log_fatigue`, `get_pareto_front`.

## TransPolymer: `TransPolymer-acee03`
- Источник: `https://github.com/ChangwenXu98/TransPolymer`, MIT. Сборку запустил агент вместе с Wan.
- Итог: 5 инструментов, 5 perfect; 14/14 тестов, 12/12 вызовов. Загружен в хаб.
- Инструменты: `embed_smiles`, `predict_property`, `finetune_property`, `tokenize_smiles`, `augment_smiles`.

## Что Alembic обошёл сам (C5)

Ни в одной из пяти сборок debugger не понадобился на этапе валидации: все инструменты прошли тесты и живые вызовы с первого прохода. Проблемы решались на этапах Explorer, Environment и Coder.

| Сборка | Проблема репозитория | Как решена |
|---|---|---|
| polyBERT | Репозиторий модели на HuggingFace без Python-пакета; `model.safetensors` и `spm.model` после клона это LFS-указатели по 134 байта | Explorer распознал указатели и описал репозиторий как model-only; Environment скачал веса через `huggingface_hub` и кэшировал их в окружении |
| polyBERT | `torch` из CPU-индекса показал версию с суффиксом cu130 | Environment проверил, что импорт и вычисления работают на CPU, и не стал переустанавливать |
| PolymerGNN | `requirements.txt` с несуществующими версиями: `torch==11.1.0`, `sklearn==0.0`; старые пины несовместимы с Python 3.11 | Environment собрал окружение с современными совместимыми версиями: torch 2.1 CPU, torch-geometric 2.4, numpy<2 |
| PolymerGNN | Код использует `captum._utils.common._format_input`, удалённый в новых версиях captum; `torch_geometric.data.makedirs` тоже удалён | Environment закрепил `captum==0.4.1`; `makedirs` нужен только модели schnet, которая в инструменты не вошла |
| mordred-community | Инструмент `setup_venv` неверно принял список пакетов | Environment передал пакеты одной строкой; полный набор из 1613 дескрипторов проверен по эталонным YAML, для этого доустановлен pyyaml |
| Wan et al. | Репозиторий без кода: три `.h5` Keras 2.4, xlsx с примерами и README | Explorer прочитал структуру моделей напрямую из HDF5 (h5py), нашёл имена входов в `config.name`, восстановил прямой проход; Coder построил инструменты по описанию входов |
| Wan et al. | Keras 3.15 из TensorFlow 2.21 не десериализует `keras.metrics.mse` из старого H5 | Environment откатил на TensorFlow 2.15.1 с Keras 2.15; предсказания сверены с xlsx авторов, расхождение ≤5e-5 |
| TransPolymer | Веса `ckpt/pretrain.pt/pytorch_model.bin` (329 МБ) и данные лежат в LFS, `git-lfs` в контейнере нет | Coder скачал содержимое напрямую с `media.githubusercontent.com`, то есть выполнил `git lfs pull` вручную |
| TransPolymer | `from transformers import AdamW` удалён в новых transformers; кастомный токенизатор тянет `vocab.json` с `roberta-base` через устаревшую карту URL | Environment и debugger (вызван на этапе окружения, 11 вызовов) закрепили transformers 4.44.2 и torch 2.14 CPU; Coder создаёт `DownstreamRegression` через подмену модульных глобалов `PretrainedModel` и `tokenizer` |
| TransPolymer | Окружение после первого прохода оказалось пустым (только pytest) | Debugger нашёл причину и доустановил pandas, regex, transformers, torch, rdkit, torchmetrics, openTSNE без правок кода |

Для сравнения: бейзлайн opencode на TransPolymer переписал токенизатор вручную под transformers 5.x, а Наргиза исключила TransPolymer из проекта из-за несовместимости версий. Alembic решил ту же проблему закреплением версий и подменой глобалов, сервер прошёл 14 тестов и 12 живых вызовов.
