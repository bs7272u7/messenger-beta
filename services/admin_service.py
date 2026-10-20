"""관리자 API가 공통으로 쓰는 입력 검증 서비스."""


class AdminServiceError(Exception):
    """관리자 입력값이 정책에 맞지 않을 때 던지는 예상 가능한 오류. 메시지는 화면에 그대로 보여 준다."""

    pass


class AdminService:
    """관리자 API의 입력 정규화와 길이 제한 규칙 모음."""

    # 허용하는 제재 종류: 경고, 24시간·7일 정지, 영구 정지, 제재 해제.
    MODERATION_ACTIONS = {"warning", "24h", "7d", "permanent", "lift"}

    @staticmethod
    def selected_ids(raw_ids, resource_name: str) -> list[int]:
        """일괄 삭제 대상 ID 목록을 검증하고 중복을 제거한다.

        빈 목록이나 잘못된 값이 들어와 의도치 않게 전체 삭제되는 일을 막기 위해,
        양의 정수만 남기고 하나도 없으면 오류로 처리한다.
        """
        if not isinstance(raw_ids, list) or not raw_ids:
            raise AdminServiceError(f"삭제할 {resource_name}를 선택해주세요.")
        try:
            selected = list({int(item) for item in raw_ids if int(item) > 0})
        except (TypeError, ValueError):
            raise AdminServiceError(f"{resource_name} 선택 정보가 올바르지 않습니다.") from None
        if not selected:
            raise AdminServiceError(f"삭제할 {resource_name}를 선택해주세요.")
        return selected

    @classmethod
    def moderation_request(cls, action, report_id, reason) -> tuple[str, int | None, str]:
        """신고 처리 요청을 DB에 저장하기 전에 안전한 값으로 정리한다.

        Returns:
            (처리 방식, 신고 ID 또는 None, 처리 사유) 튜플.
        """
        if action not in cls.MODERATION_ACTIONS:
            raise AdminServiceError("지원하지 않는 처리 방식입니다.")
        try:
            normalized_report_id = int(report_id) if report_id is not None else None
        except (TypeError, ValueError):
            raise AdminServiceError("신고 처리 정보를 확인할 수 없습니다.") from None
        # 사유를 비워 보내면 기본 문구로 채운다.
        normalized_reason = (reason or "관리자 운영 정책 위반").strip()
        # 사유는 제재 기록과 사용자 안내 메시지에 그대로 쓰이므로 길이를 제한한다.
        if len(normalized_reason) > 500:
            raise AdminServiceError("처리 사유는 500자 이하로 입력해주세요.")
        return action, normalized_report_id, normalized_reason

    @staticmethod
    def notice_content(title, content) -> tuple[str, str]:
        """공지 제목·내용이 비어 있거나 너무 길면 저장하지 않도록 검사한다."""
        title = (title or "").strip()
        content = (content or "").strip()
        if not title or not content:
            raise AdminServiceError("제목과 내용을 입력해주세요.")
        if len(title) > 200 or len(content) > 5000:
            raise AdminServiceError("공지사항 길이를 확인해주세요.")
        return title, content
