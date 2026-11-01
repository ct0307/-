"""先落盘图状态，再记录已提交事件；恢复时允许补记事件。"""
from langgraph.checkpoint.sqlite import SqliteSaver


class ObservedSqliteSaver(SqliteSaver):
    def __init__(self, connection, on_commit):
        super().__init__(connection)
        self.on_commit = on_commit

    def put(self, config, checkpoint, metadata, new_versions):
        result = super().put(config, checkpoint, metadata, new_versions)
        # 该回调失败时检查点已经保存。恢复入口按 checkpoint id 幂等补记。
        self.on_commit(checkpoint)
        return result
