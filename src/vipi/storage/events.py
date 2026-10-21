"""Transport-independent replay of run progress."""


class EventLog:
    def iter_events(self, after=0):
        while True:
            with self.condition:
                batch = self.events[after:]
                terminal = self.status["state"] in {"completed", "failed"}
                if not batch and not terminal:
                    self.condition.wait(timeout=15)
                    batch = self.events[after:]
                    terminal = self.status["state"] in {"completed", "failed"}
            for event in batch:
                yield event
                after = event["id"]
            if terminal:
                return
            if not batch:
                yield None
