import re
import time
from datetime import datetime, timedelta

from module.base.timer import Timer
from module.exception import TaskEnd
from module.logger import logger
from tasks.GameUi.game_ui import GameUi
from tasks.GameUi.page import page_main
from tasks.GuildActivityMonitor.assets import GuildActivityMonitorAssets

class ScriptTask(GameUi, GuildActivityMonitorAssets):

    def run(self):
        """阴阳寮活动监控主函数"""
        if not self.check_run_days():
            raise TaskEnd('GuildActivityMonitor')
        self.goto_page(page_main)
        keyword_map = self.build_keyword_map()
        self.monitor_activities(keyword_map)

    def check_run_days(self) -> bool:
        """检查今天是否在运行日期内，设置下次运行时间"""
        monitor_config = self.config.guild_activity_monitor.guild_activity_monitor_combat_time
        now = datetime.now()
        today = now.weekday() + 1
        run_days = sorted({day for day in map(int, re.findall(r'\d+', monitor_config.run_days)) if 1 <= day <= 7})
        if not run_days:
            logger.warning(f"运行日期配置无效: {monitor_config.run_days}，跳过 GuildActivityMonitor")
            return False

        in_run_days = today in run_days
        candidate_days = [day for day in run_days if day != today] if in_run_days else run_days
        delta_days = min((day - today) % 7 for day in candidate_days)
        next_date = now + timedelta(days=delta_days or 7)

        server_update = self.config.guild_activity_monitor.scheduler.server_update
        use_server_time = (server_update.hour, server_update.minute, server_update.second) != (9, 0, 0)
        next_target = datetime.combine(next_date.date(), server_update) if use_server_time else next_date
        status = '在' if in_run_days else '不在'
        action = '本次继续执行' if in_run_days else '跳过 GuildActivityMonitor'
        logger.info(f"今天是周{today}，{status}配置运行日期({monitor_config.run_days})内，"
                    f"{action}，下次运行时间: {next_target}")
        self.set_next_run(task='GuildActivityMonitor', success=None, finish=False, server=False, target=next_target)
        return in_run_days

    def build_keyword_map(self) -> dict:
        """构建活动关键字到任务名的映射"""
        guild_config = self.config.guild_activity_monitor.guild_activity
        keyword_map = {
            '道馆': 'Dokan' if guild_config.Dokan else None,
            '狭间': 'AbyssShadows' if guild_config.AbyssShadows else None,
            '宴会': 'GuildBanquet' if guild_config.GuildBanquet else None,
            '退治': 'DemonRetreat' if guild_config.DemonRetreat else None,
        }
        keyword_map = {k: v for k, v in keyword_map.items() if v}
        logger.info(f"监控活动: {list(keyword_map.keys())}")
        return keyword_map

    def monitor_activities(self, keyword_map: dict):
        """启动活动监控循环"""
        monitor_config = self.config.guild_activity_monitor.guild_activity_monitor_combat_time
        interval = monitor_config.detection_interval
        use_ocr = monitor_config.use_ocr
        keywords = list(keyword_map.keys())
        logger.info(f"开始阴阳寮活动监控，持续{monitor_config.monitor_duration}分钟，"
                    f"每{interval}秒检测一次，模式: {'ocr' if use_ocr else 'adb'}")

        check_timer = Timer(monitor_config.monitor_duration * 60)
        check_timer.start()
        log_timer = Timer(60)
        log_timer.start()

        stuck_interval = Timer(280)
        while True:
            if not stuck_interval.started() or stuck_interval.reached():
                self.device.stuck_record_clear()
                self.device.stuck_record_add('PAUSE')
                stuck_interval.reset()

            if check_timer.reached():
                logger.info("监控时间到，任务结束")
                raise TaskEnd('GuildActivityMonitor')

            if log_timer.reached():
                remaining = int(check_timer.remain() // 60)
                logger.info(f"监控中... 剩余时间: {remaining}分钟")
                log_timer.reset()

            self.screenshot()
            current_text = self.get_ocr_text()
            if current_text:
                for keyword, task_name in KEYWORD_MAP.items():
                    if keyword in current_text:
                        logger.info(f"检测到关键字 '{keyword}'，启动任务: {task_name}")
                        self.set_next_run(task=task_name, success=False, finish=False, server=False, target=datetime.now())
                        recheck_interval = monitor_config.recheck_interval
                        self.set_next_run(task='GuildActivityMonitor', success=False, finish=False, server=False, target=datetime.now() + timedelta(minutes=recheck_interval))
                        raise TaskEnd('GuildActivityMonitor')

            time.sleep(interval)

    def get_ocr_text(self) -> str:
        """截取指定区域并返回 OCR 识别文本"""
        try:
            self.screenshot()
            DOKAN = self.O_GUILD_DOKAN.ocr(self.device.image)
            if DOKAN != (0,0,0,0):
                return '道馆'
            ABYSS = self.O_GUILD_ABYSS.ocr(self.device.image)
            if ABYSS != (0,0,0,0):
                return '狭间'
            BANQUET = self.O_GUILD_BANQUET.ocr(self.device.image)
            if BANQUET != (0,0,0,0):
                return '宴会'
            RETREAT = self.O_GUILD_DEMON_RETREAT.ocr(self.device.image)
            if RETREAT != (0,0,0,0):
                return '退治'
            raise ValueError("未监控到任务")
        except Exception as e:
            return "未监控到任务"

if __name__ == '__main__':
    from module.config.config import Config
    from module.device.device import Device

    c = Config('oas1')
    d = Device(c)
    t = ScriptTask(c, d)
    t.run()
