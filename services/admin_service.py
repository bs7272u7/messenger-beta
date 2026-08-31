"""관리자 전용 입력 검증을 공통화하는 서비스."""


class AdminServiceError(Exception):
    """관리자 입력값이 정책을 만족하지 않을 때 반환하는 예상 가능한 오류입니다."""


class AdminService:
    """관리자 API가 공통으로 쓰는 입력 정규화·길이 제한 규칙입니다."""

    MODERATION_ACTIONS = {"warning", "24h", "7d", "permanent", "lift"}

    @staticmethod
    def selected_ids(raw_ids, resource_name: str) -> list[int]:
        """일괄 삭제 대상이 빈 목록이나 잘못된 값으로 전체 삭제되는 것을 막는다."""
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
        """신고 처리 요청을 DB 저장 전 안전한 값으로 정리합니다."""
        if action not in cls.MODERATION_ACTIONS:
            raise AdminServiceError("지원하지 않는 처리 방식입니다.")
        try:
            normalized_report_id = int(report_id) if report_id is not None else None
        except (TypeError, ValueError):
            raise AdminServiceError("신고 처리 정보를 확인할 수 없습니다.") from None
        normalized_reason = (reason or "관리자 운영 정책 위반").strip()
        if len(normalized_reason) > 500:
            raise AdminServiceError("처리 사유는 500자 이하로 입력해주세요.")
        return action, normalized_report_id, normalized_reason

    @staticmethod
    def notice_content(title, content) -> tuple[str, str]:
        """빈 공지나 지나치게 큰 공지가 저장되지 않도록 검사합니다."""
        title = (title or "").strip()
        content = (content or "").strip()
        if not title or not content:
            raise AdminServiceError("제목과 내용을 입력해주세요.")
        if len(title) > 200 or len(content) > 5000:
            raise AdminServiceError("공지사항 길이를 확인해주세요.")
        return title, content
