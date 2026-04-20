PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE ai_batches (
            batch_id TEXT PRIMARY KEY,
            request_id TEXT,
            ai_provider TEXT,
            model_name TEXT,
            prompt_version TEXT,
            batch_size INTEGER,
            total_latency_ms INTEGER,
            prompt_tokens INTEGER,
            completion_tokens INTEGER,
            total_tokens INTEGER,
            finish_reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
INSERT INTO "ai_batches" VALUES('c8b2156d-09f5-493d-81f8-45135cb61fa9','644a0360e02d4ebc8c5c0e26afa0f8da','mimo','mimo-v2-flash','a7c934c9',1,29389,0,0,2271,'stop','2026-04-10 02:07:18');
CREATE TABLE ai_word_notes (
            voc_id TEXT PRIMARY KEY,
            spelling TEXT,
            basic_meanings TEXT,
            ielts_focus TEXT,
            collocations TEXT,
            traps TEXT,
            synonyms TEXT,
            discrimination TEXT,
            example_sentences TEXT,
            memory_aid TEXT,
            word_ratings TEXT,
            raw_full_text TEXT,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            batch_id TEXT,
            original_meanings TEXT,
            maimemo_context TEXT,
            it_level INTEGER DEFAULT 0,
            it_history TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
INSERT INTO "ai_word_notes" VALUES('voc-yy83gSLZY3k0reLq-6yrjE4TO6ck6S58movzJPTo2so1d8-qHDXXknFA5vK4jcMD','altitude','n. 海拔高度；高空 (at high altitude; altitude sickness; altitude of 5,000 meters)
n. [生僻] 地平纬度 (celestial altitude)','• 核心考试逻辑：altitude 在 IELTS 中主要作为地理和航空术语出现，尤其在阅读（地理、环境、科技）和听力（旅游、航空）中高频。
• 固定测试模式：常与 ''high''、''low''、''maximum'' 搭配，描述地理特征或健康影响（如 altitude sickness）。
• 技能上下文：在写作中用于描述环境或地理变化（如气候变化对海拔的影响）；在口语中用于描述旅行经历。','high altitude：高海拔（用于描述地理区域或飞行高度，常见于环境或旅游话题）
altitude sickness：高原反应（医学/旅游话题，解释健康风险）
at an altitude of：在...海拔高度（精确描述位置，用于地理或航空写作）
maximum altitude：最大高度（科技或航空上下文，如描述飞机性能）','Trap: 易与 ''attitude''（态度）混淆，拼写仅差一字，但 ''altitude'' 是名词（高度），''attitude'' 是名词（态度）或航空术语（姿态）。在 IELTS 听力或阅读中，需根据上下文区分，避免因拼写错误失分。','at high altitude → at elevated heights / in lofty regions','altitude vs height：altitude 侧重于海拔高度（通常相对于海平面，用于地理或航空专业语境）；而 height 侧重于一般垂直距离（可指物体高度、人物身高，更通用且日常）。','[Writing Task 2 Context]: The impact of climate change on high altitude ecosystems is a pressing issue that requires immediate global action. [气候变化对高海拔生态系统的影响是一个需要全球立即行动的紧迫问题。]
[Speaking Context]: I experienced altitude sickness when I traveled to Tibet last year, but the breathtaking views made it worthwhile. [我去年去西藏旅行时经历了高原反应，但令人惊叹的景色让一切值得。]','记忆法一（核心逻辑）： ''Altitude'' 的核心是''高度''，所有含义都围绕''垂直距离''展开，无论是地理海拔还是航空高度。
记忆法二（词根词缀/构词法）： 源自拉丁语 ''altus''（高的），与 ''altitude'' 同根的词有 ''altimeter''（高度计），帮助记忆其测量高度的含义。
记忆法三（场景/图像联想）： 想象一架飞机飞越喜马拉雅山脉，仪表盘显示 ''altitude: 10,000 meters''，同时你感到轻微的 altitude sickness，这个场景将高度、航空和健康影响联系在一起。','• 提分杠杆率 (ROI): 8/10 - 该词在地理和环境话题中高频出现，掌握后能显著提升阅读和写作的准确性。
• 学术输出潜力 (Academic Yield): 7/10 - 适用于科技和环境类学术写作，但使用场景相对特定。
• 易错踩坑指数 (Trap Probability): 6/10 - 与 ''attitude'' 拼写相似，需注意区分，但上下文通常能帮助识别。','### altitude

n. 海拔高度；高空 (at high altitude; altitude sickness; altitude of 5,000 meters)
n. [生僻] 地平纬度 (celestial altitude)

**[IELTS FOCUS]**
- 核心考试逻辑：altitude 在 IELTS 中主要作为地理和航空术语出现，尤其在阅读（地理、环境、科技）和听力（旅游、航空）中高频。
- 固定测试模式：常与 ''high''、''low''、''maximum'' 搭配，描述地理特征或健康影响（如 altitude sickness）。
- 技能上下文：在写作中用于描述环境或地理变化（如气候变化对海拔的影响）；在口语中用于描述旅行经历。

**[COLLOCATIONS]**
**high altitude**：高海拔（用于描述地理区域或飞行高度，常见于环境或旅游话题）
**altitude sickness**：高原反应（医学/旅游话题，解释健康风险）
**at an altitude of**：在...海拔高度（精确描述位置，用于地理或航空写作）
**maximum altitude**：最大高度（科技或航空上下文，如描述飞机性能）

**[TRAPS]**
**Trap:** 易与 ''attitude''（态度）混淆，拼写仅差一字，但 ''altitude'' 是名词（高度），''attitude'' 是名词（态度）或航空术语（姿态）。在 IELTS 听力或阅读中，需根据上下文区分，避免因拼写错误失分。

**[SYNONYMS]**
**at high altitude** → **at elevated heights** / **in lofty regions**

**[DISCRIMINATION]**
**altitude** vs **height**：**altitude** 侧重于海拔高度（通常相对于海平面，用于地理或航空专业语境）；而 **height** 侧重于一般垂直距离（可指物体高度、人物身高，更通用且日常）。

**[EXAMPLE SENTENCES]**
*[Writing Task 2 Context]: The impact of climate change on **high altitude** ecosystems is a pressing issue that requires immediate global action. [气候变化对高海拔生态系统的影响是一个需要全球立即行动的紧迫问题。]
*[Speaking Context]: I experienced **altitude sickness** when I traveled to Tibet last year, but the breathtaking views made it worthwhile. [我去年去西藏旅行时经历了高原反应，但令人惊叹的景色让一切值得。]

**[MEMORY AID]**
**记忆法一（核心逻辑）：** ''Altitude'' 的核心是''高度''，所有含义都围绕''垂直距离''展开，无论是地理海拔还是航空高度。
**记忆法二（词根词缀/构词法）：** 源自拉丁语 ''altus''（高的），与 ''altitude'' 同根的词有 ''altimeter''（高度计），帮助记忆其测量高度的含义。
**记忆法三（场景/图像联想）：** 想象一架飞机飞越喜马拉雅山脉，仪表盘显示 ''altitude: 10,000 meters''，同时你感到轻微的 altitude sickness，这个场景将高度、航空和健康影响联系在一起。

**[WORD RATINGS]**
- **提分杠杆率 (ROI): 8/10** - 该词在地理和环境话题中高频出现，掌握后能显著提升阅读和写作的准确性。
- **学术输出潜力 (Academic Yield): 7/10** - 适用于科技和环境类学术写作，但使用场景相对特定。
- **易错踩坑指数 (Trap Probability): 6/10** - 与 ''attitude'' 拼写相似，需注意区分，但上下文通常能帮助识别。

',1475,796,2271,'c8b2156d-09f5-493d-81f8-45135cb61fa9',NULL,'{"review_count": null, "short_term_familiarity": null}',0,NULL,'2026-04-10 02:07:18','2026-04-10 10:07:18');
CREATE TABLE processed_words (
            voc_id TEXT PRIMARY KEY,
            spelling TEXT,
            processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
INSERT INTO "processed_words" VALUES('voc-yy83gSLZY3k0reLq-6yrjE4TO6ck6S58movzJPTo2so1d8-qHDXXknFA5vK4jcMD','altitude','2026-04-10 02:07:19');
CREATE TABLE test_run_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_count INTEGER,
            sample_count INTEGER,
            sample_words TEXT,
            ai_calls INTEGER,
            success_parsed INTEGER,
            is_dry_run BOOLEAN,
            error_msg TEXT,
            ai_results_json TEXT
        );
CREATE TABLE word_progress_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voc_id TEXT,
            familiarity_short FLOAT,
            familiarity_long FLOAT,
            review_count INTEGER,
            it_level INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
INSERT INTO "word_progress_history" VALUES(1,'voc-yy83gSLZY3k0reLq-6yrjE4TO6ck6S58movzJPTo2so1d8-qHDXXknFA5vK4jcMD',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(2,'voc-6P_uJnIZ2ocUAsdcUdIUkJPNE5CrMgJn0cHHPmATRuxEqGvbxHuPqOrlY-1lZ2aD',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(3,'voc-H0E9ot014dnNoFpMOJCs9ASyQWPTSK6WqrHJ_tl0NXeQ354WHsbM8sP8kp4FBncX',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(4,'voc-6P_uJnIZ2ocUAsdcUdIUkCaBquEG92R8hhqDEoAJyH_2tXb7JzbIh7POWQJVeTkx',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(5,'voc-yn5ie3gtTeqFYk-QslQzPKAXoqleJnPP5ypBoawusCWDpuXSaJeBFwjq5lM_2t2z',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(6,'voc-H0E9ot014dnNoFpMOJCs9BIXOcVXsavXnnqZD490XtMzX6YeCL5Wkn9IxRvi-OlJ',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(7,'voc-k8DfKk3CYMESS21uHE_tTNxFWZBIxoroby5-ZAVmkDZuf3ur11w35DREW_g8g_cd',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(8,'voc-Ae5YdCRF8Flu9Zzp8wW3ehkgV-9qg_bevNUMOhG-et_ogVg2P8fSiK8j2gv6nwOt',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(9,'voc-snlbFTvQuKoaxpnxHRa1lWAMEYYC821iqJK2hmIcmZ35UWiDFy6Jj8DAt1BElMAt',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(10,'voc-yy83gSLZY3k0reLq-6yrjHlysnd6ygAVGbCWWshBnxxhvmJkN1N6epDyhffvEK_h',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(11,'voc-j787I4Ru6r3A4NG5eQWk8MWDQg98yDYE5rAVX3XaAZtn-Xn4v-caxFeN6EWobSlo',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(12,'voc-yn5ie3gtTeqFYk-QslQzPDryZc0QMdYHKm99rKjsd5eehYOuoNgc_OJfAw92O40h',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(13,'voc-yy83gSLZY3k0reLq-6yrjLXyLzjRKk7vZ9nplz5-1ital-CEPcp9ZLS9XDfDv7Xu',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(14,'voc-yy83gSLZY3k0reLq-6yrjHlysnd6ygAVGbCWWshBnxyjtRw5l7E0GI1llx-rkckf',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(15,'voc-k8DfKk3CYMESS21uHE_tTNSW_nSsBf1C4-zY9r_wffME9htLfUb0k4lvTcGYs9Xv',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(16,'voc-ccaIlQ_jB8ybztKa31AQlLmFg2IbZ_Ghl6rRgDPKVhTGkz6X6Liw8HQ0kuqdYoqT',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(17,'voc-ccaIlQ_jB8ybztKa31AQlBRNAWhiD3gNHzPrsxd_lFelKB_smgvYroZQIWJQgR3L',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(18,'voc-yn5ie3gtTeqFYk-QslQzPIlmg4GOyUhxHxy3B2ahWSoTZ1hK_VunAwnBe9FG5r_Z',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(19,'voc-cmUrd_5ZuylnhjvIX805G_ZpS_ROflUFj6tkq58W_W0yTXEFwGMlKo_rpbhV9YWb',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(20,'voc-Ae5YdCRF8Flu9Zzp8wW3eqUmxZym19s8jfKc8qsswbSd3-dLlVKf3NGxqcmUpIH8',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(21,'voc-H0E9ot014dnNoFpMOJCs9KdAtkTMQzawDPYo-bK40SKYf7S67Psa1c3LQWyRLNsL',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(22,'voc-Ae5YdCRF8Flu9Zzp8wW3egNsGu9Bl9Fd-I9vLtifGh0UpJHiAxcBSMrVvvkKSzhU',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(23,'voc-Ae5YdCRF8Flu9Zzp8wW3eh_dhArYxddojobNLnFSKL6E7zVjSreQmcAqexk4ehM2',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(24,'voc-k8DfKk3CYMESS21uHE_tTGPv1cTZiVsQBiI__xhoH_Wp697ORCLasmNwdLpWy8hS',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(25,'voc-k8DfKk3CYMESS21uHE_tTF05AfkeGutPyIAHsFiQUpOI5cIbHmNX_UJzmm3O7QT_',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(26,'voc-ccaIlQ_jB8ybztKa31AQlEM0bJ9oriz_jJBf-v1a_wiEpdoUrE8hNgMav_drgTmp',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(27,'voc-Ae5YdCRF8Flu9Zzp8wW3evJEE3vdbi1-L2HSFJjf7DINZDAlV9kM3khIlp4xHb15',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(28,'voc-yy83gSLZY3k0reLq-6yrjLFPqqRAgXF_1tW_VUMEAM9jiUPEyAfHxnaJ6AJKql6d',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(29,'voc-ccaIlQ_jB8ybztKa31AQlAxa18hF-PAKnIwmvg7WOm_PIDK8c0eJkZc1gCO-Mmm0',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(30,'voc-yn5ie3gtTeqFYk-QslQzPFvdcG2-AM9W220fIF2sFft-hFWg4Yjn_B1vzPpj2EUz',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(31,'voc-yn5ie3gtTeqFYk-QslQzPN_o5Y4nt7pei4nhLZPwuE1GuEIxhmcMYLGX0y8QynIT',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(32,'voc-yy83gSLZY3k0reLq-6yrjI9fNqBz4UNCl5uEoJDuuVSqa4CxLNxCoBDIjjxJ6SZ9',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(33,'voc-yy83gSLZY3k0reLq-6yrjOjsyqfgg9OdVT2Zayoe1BjMB1fPUbUVSSLwNA_FJ72n',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(34,'voc-yy83gSLZY3k0reLq-6yrjGhKo6UhNU5u_Q7ub1IFlJKeKIR5XNT_gMjkqZH9b1Xd',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(35,'voc-k8DfKk3CYMESS21uHE_tTB-Jx6uFp7Rl4PfTjNqg1syllpCKXPxqTw__lylcGFsG',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(36,'voc-H0E9ot014dnNoFpMOJCs9LtM2Cq1Jne5in7mCSADr34_45Idwb6pZScQeZhoyfRt',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(37,'voc-yn5ie3gtTeqFYk-QslQzPHtTf2aATTOcIYrX2weup8KeMVSzDBtJVtVDj_nc4Shu',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(38,'voc-yy83gSLZY3k0reLq-6yrjBv18dYz3TusCOoHJ7bbqjW8NLH_XUQ8QcUH290BZd3W',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(39,'voc-k8DfKk3CYMESS21uHE_tTNHn3gQTVfU0khSZxOtKMlVfjJpNteAfq2MoIDkhNGS_',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(40,'voc-k8DfKk3CYMESS21uHE_tTPtc3eFKUsPywHKs8FurMkwJzsI-qhLUWbcXpbZb4LBN',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(41,'voc-Ae5YdCRF8Flu9Zzp8wW3eg1pG5a1-fFqiUtIlG6Ryvt3-kEmUi6lJ4fovuCJTm81',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(42,'voc-yn5ie3gtTeqFYk-QslQzPGc2_QqNELNwVsZO_ziu7LcbZsOadaIulY6UveBj3XES',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(43,'voc-k8DfKk3CYMESS21uHE_tTFeHWgNi_-y3eV1ppiAW1CDl4TL5rUQkRDfqZC0lTvyA',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(44,'voc-ccaIlQ_jB8ybztKa31AQlJf0gzLIGz6sMx34b45sGeBd4WAZR3O1ogg_e-IPa3GB',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(45,'voc-eVAh2UfQB0WMpmKi2SXaM_-82ZGxC2-wHX4X2tZw8hONYYimdFcltJKZuWtMWxkt',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(46,'voc-H0E9ot014dnNoFpMOJCs9AYGcH68TFUKhLVlPKTRUs9o453_vIQes1bhzQee3VaD',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(47,'voc-yy83gSLZY3k0reLq-6yrjCS1HAMZbLy4fTOeCaul0lI5FDDp6DkfT5GN188PogOK',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(48,'voc-yy83gSLZY3k0reLq-6yrjG5hzrLMsBUQokO9gSKTSnayXKrcz98Rk4-7IZXshxY9',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(49,'voc-k8DfKk3CYMESS21uHE_tTF05AfkeGutPyIAHsFiQUpMigPSqXEpmlIDSkcNJuWQ1',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(50,'voc-H0E9ot014dnNoFpMOJCs9AsXMlgUHpw4k9R2jYn9i9pFfK1L5epzGEDRsHzU0gwN',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(51,'voc-ccaIlQ_jB8ybztKa31AQlGkiYFpV5ALuv5CVdyWPFjg8nknbG9KISjzi9p-kGPrs',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(52,'voc-yn5ie3gtTeqFYk-QslQzPBs9TDy7uhHVkCQhYB2h25k-J0nEdg3WHYSQ0Wbw1Dv1',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(53,'voc-yn5ie3gtTeqFYk-QslQzPHtTf2aATTOcIYrX2weup8JBOoeo_fin9nNJAAFqI3L-',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(54,'voc-yy83gSLZY3k0reLq-6yrjBnovOCPDUu7QrGS9_w6-v1C2fvzTM52xp38Xnxqv3ti',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(55,'voc-k8DfKk3CYMESS21uHE_tTEu119kULEDWB2M3yabrg0mzTR-MFojaqVTMEyw801n2',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(56,'voc-Ae5YdCRF8Flu9Zzp8wW3ekjXEbwysyaE6dSfu_vDnntg_U4-k4sp3W1B-ZeylrLj',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(57,'voc-ZlQJRTsVy6U4H1ARRB-SSFH2CMqpEJ0g_WAAyyYBjW3ZkGVkx5Q14cHvXSMK47ys',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(58,'voc-H92_JoVNLa8MFC9fhsZ6_TUTaSYsR8yj0wjcHWkqKXESnaoeOaSAURrrIumhg0Md',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(59,'voc-cmUrd_5ZuylnhjvIX805G1Gfo7JGXFXex0qvckuaqRkHb6Ct1OnZS03q2I6A8P2b',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(60,'voc-H0E9ot014dnNoFpMOJCs9OzFZiiOFKA7U5rDn-WZM6eyx3kAZYVxmvz5hXYMYd7v',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(61,'voc-yn5ie3gtTeqFYk-QslQzPKmZOpcY0ZTILRtifV6GWMiPyUBQVC3Oi788__ze3CC-',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(62,'voc-yn5ie3gtTeqFYk-QslQzPBSxn76jNn1hUhLA9rKnM_GnWOp_NY2xHzVS0TYkuUwQ',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(63,'voc-ccaIlQ_jB8ybztKa31AQlHfeVxbxqk-q4hI98iSdcJ5t9y_qElglQ4CI5VsYLZkq',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(64,'voc-ZlQJRTsVy6U4H1ARRB-SSJs3J37030iPEK-n_BwvseGUq8vv4b_5QgsRH9zibosP',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(65,'voc-ZlQJRTsVy6U4H1ARRB-SSFvJIoMP-4BtFr7uWYfRONoJc0YAC2zTF15gUO8aScoM',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(66,'voc-yy83gSLZY3k0reLq-6yrjIteo6b0xLJ8j-0nhfXsmOPc296_RVtATKyX_B7p_5WY',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(67,'voc-snlbFTvQuKoaxpnxHRa1lR7AtHSKodLcITEWycVPBuJBwvHobS1XwD-GiU_lK1gt',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(68,'voc-cmUrd_5ZuylnhjvIX805G1Dmx2S0CQR_pTsnFX9-L9K_2TcOisxoT3nmQCy9Hq4E',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(69,'voc-Ae5YdCRF8Flu9Zzp8wW3emPUNSbPDOxyvVG_QA5cSbA4NJ3IGzGfAh31CNVAPtRW',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(70,'voc-j787I4Ru6r3A4NG5eQWk8Bv4cyTaYdhYa2fsGSMftIpF1XmoYfz1q3rvsO5NURPP',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(71,'voc-H0E9ot014dnNoFpMOJCs9HjQDeSUlCFuDcZylNfaxcFMGQ1kAZGZtx7hPmt9JDXj',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(72,'voc-ZlQJRTsVy6U4H1ARRB-SSEBv5471yxFSsn7G5hPDlDNxUl9_nrdjCPx2tdWnB_N2',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(73,'voc-H0E9ot014dnNoFpMOJCs9AvSznn83YDzY9K45FcdRmm31R6jewZmw30SlGp1m_WT',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(74,'voc-yn5ie3gtTeqFYk-QslQzPGXuc3HmWZMLQxzIkAaEXr_ll3qvXVLDzEjWL2ZZuO7Y',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(75,'voc-k8DfKk3CYMESS21uHE_tTGyzHdDpRjrjF8u1LWfU-Zu3pNeuf0MvsEGAD2ALIPh-',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(76,'voc-Ae5YdCRF8Flu9Zzp8wW3egw2VNfAmSwOm3n_bl0Zag5U1l5tfxQQF2E8zjA2tDKh',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(77,'voc-yy83gSLZY3k0reLq-6yrjPIYP96o2-hJsC71fpb7q-nIss3MSUoZrMkXZhTiT8iR',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(78,'voc-yy83gSLZY3k0reLq-6yrjLXyLzjRKk7vZ9nplz5-1iuuGf7vfTjkveIK9CLqRmk7',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(79,'voc-eVAh2UfQB0WMpmKi2SXaM5LFN0jSoWKDmuv4Mnlu-lbM2SMXY1ChKXSHQ8ZBvInz',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(80,'voc-yy83gSLZY3k0reLq-6yrjG5hzrLMsBUQokO9gSKTSnbtcjjmAvBYNWjoHqSh5B2u',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(81,'voc-k8DfKk3CYMESS21uHE_tTKoZe3Bv06zrqiqWKgiFiJRyMM3mlWZcTjYB6BSzJGgs',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(82,'voc-k8DfKk3CYMESS21uHE_tTGGOv63Ip6znsXeCY1ngrDFf7bMpoKpEQfgdiA3d4Wfh',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(83,'voc-ccaIlQ_jB8ybztKa31AQlChCZ8glOeJN9syT0pim1wTGcq1bexX8KnCy0RwfkvXl',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(84,'voc-pxC29XeY_PGOekafldh_jh4odqqnIIpU6GuGYNclK3IMEo3_TcRogR1WCZyuhT1G',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(85,'voc-k8DfKk3CYMESS21uHE_tTPtc3eFKUsPywHKs8FurMkwpUoELrWBqzsmpB78SPgay',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(86,'voc-k8DfKk3CYMESS21uHE_tTPtc3eFKUsPywHKs8FurMkxJ78UGtcqR9CtsNQXH7Ao3',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(87,'voc-Ae5YdCRF8Flu9Zzp8wW3ei7Rpb2XmWPBsX0VmbXmRNHdvd_Ii_5tQnXkHu7QHZhP',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(88,'voc-lHxYt-OJFnUK6qYSNagacKW_-4iaRwNwN-gN0swoGJXHd94Lv2_BhvK-fM6dfaf6',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(89,'voc-j787I4Ru6r3A4NG5eQWk8MzUj_INz9YP-J03zamkdWquIHR4UfqYPSTYbKucVxym',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(90,'voc-ccaIlQ_jB8ybztKa31AQlL687J6h3mgK512x9JnCrlM0KDYS-CtjuoRwaTLJIhaD',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(91,'voc-ZlQJRTsVy6U4H1ARRB-SSL8D580VOxXzHZI2OaqGcVUeCuXwpUfm2t-fr27XV77B',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(92,'voc-6P_uJnIZ2ocUAsdcUdIUkJPNE5CrMgJn0cHHPmATRuz_FUrueXZCSw-v2N7R4Bvp',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(93,'voc-yy83gSLZY3k0reLq-6yrjIY64RQyoBPCWQLJJppU2mKNq1VD01-wZhiAj7lW_Jah',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(94,'voc-Ae5YdCRF8Flu9Zzp8wW3etYWM5D7hOEcYodWx7EUp0Ok1T5qZIMgk3mQWLtj1YxH',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(95,'voc-k8DfKk3CYMESS21uHE_tTAaErt7jdhT5ekf1x8qIiyEZPyWcOPKwBSIgRqsrcc5U',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(96,'voc-yn5ie3gtTeqFYk-QslQzPKNF_2u8ouYB8bI-hoCAKaNYbVmUDf_rPvsk94hizuIJ',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(97,'voc-cmUrd_5ZuylnhjvIX805G6zbS4dZi-x-VDXOAIun2e223csfIKvMqfawMyWy8Sxt',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(98,'voc-yn5ie3gtTeqFYk-QslQzPL2ZYf4bFoqJkYJP0SLUPklpG1KkhaQ1j6aIi7h_RvGE',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(99,'voc-ccaIlQ_jB8ybztKa31AQlLEXKQgiCIBseKOiBMvbcimhOyptsj9gRTnKnYU48Mr8',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(100,'voc-k8DfKk3CYMESS21uHE_tTAifa8zIcbd3XrJ5amguDRLUN-CWaSjRTB_15_IZpJbU',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(101,'voc-ZlQJRTsVy6U4H1ARRB-SSG6aRfmDINg2X_Q8kES7y30G7TjoLkztPrETixZ3Q_up',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(102,'voc-ccaIlQ_jB8ybztKa31AQlBCrTd0NqXkusHkH6L8N3q9TbHqxu2U8dL8clGNr-ODs',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(103,'voc-6P_uJnIZ2ocUAsdcUdIUkMKFGxswnNRpR77VFe6pcIPX8uZ6Wb_k4iBzv7O0hguK',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(104,'voc-Ae5YdCRF8Flu9Zzp8wW3egw2VNfAmSwOm3n_bl0Zag4M-WqfRwhauovl11MH2BcP',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(105,'voc-yn5ie3gtTeqFYk-QslQzPLc1ZFesnuapDO7ZyXM0v_DwHBEAuP0yIPw0jgH7FrJN',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(106,'voc-k8DfKk3CYMESS21uHE_tTNxFWZBIxoroby5-ZAVmkDajyR54U56ldO5RsiXOa-T0',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(107,'voc-H0E9ot014dnNoFpMOJCs9GjQIXbhGtQlcS4FxQFgJWB9BzjSnZF9SFj03jUTHvLo',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(108,'voc-yn5ie3gtTeqFYk-QslQzPKAXoqleJnPP5ypBoawusCWx-6BWEcCYGJplwm16Gc02',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(109,'voc-yn5ie3gtTeqFYk-QslQzPIuhCCEadv5esw3b6UQj3mY-7-Vg_iEVCw_-ErexJyG3',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(110,'voc-yn5ie3gtTeqFYk-QslQzPJzgV-speZQdm5V0xgJZYXPKsTShpELcUiLuqYIjLHj7',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(111,'voc-ccaIlQ_jB8ybztKa31AQlHfeVxbxqk-q4hI98iSdcJ7fVDngPcWeBGmUXpq-50k6',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(112,'voc-yn5ie3gtTeqFYk-QslQzPEhFyHa3EIUTcmd2nEYrcQilwp8H3TJwyQCWsHwqtAen',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(113,'voc-ZlQJRTsVy6U4H1ARRB-SSDepCUkSUQMGGH9kHc6yArGFnY2bSYBswXxR4kJojh_d',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(114,'voc-yn5ie3gtTeqFYk-QslQzPMrzmck6VSdOE2fDrMyAVy10913_xKvqGp-7N6ibFtc-',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(115,'voc-yy83gSLZY3k0reLq-6yrjCscExQK79J7P0HpFaEuRj3cxE2ZX_Ce5eDQLDAduLW6',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(116,'voc-H0E9ot014dnNoFpMOJCs9P2smfaqfuz3KGRu2WzpIRjAp5_uLDHrDsndhFa2FjK2',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(117,'voc-Ae5YdCRF8Flu9Zzp8wW3esLWNlPJrLaMFm0s6Re2SkSHIK0XUHVrXS-k-LAXXQUN',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(118,'voc-6P_uJnIZ2ocUAsdcUdIUkLhtV9QttJIm_Y2ejKSyX6gJG8bIUuQLa0LMg_GGVTXh',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(119,'voc-snlbFTvQuKoaxpnxHRa1laWOB7GSrEBsSURhnepayxP8TM7wyXsKiI2iOi3vHO5b',0.0,0.0,0,0,'2026-04-10 02:06:48');
INSERT INTO "word_progress_history" VALUES(120,'voc-ZlQJRTsVy6U4H1ARRB-SSFm6gkVCDVeEpuIdOz2rD_l00Bfw4vDeGrJHX-Urjkfm',0.0,0.0,0,0,'2026-04-10 02:06:48');
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('word_progress_history',120);
COMMIT;
