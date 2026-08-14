/*
 * Cloud Chatting의 화면 언어를 한곳에서 관리한다.
 * 사용자 메시지와 이름은 번역하지 않고, 서비스가 직접 만든 안내 문구만 바꾼다.
 */
(function () {
    const supportedLanguages = new Set(["ko", "en", "zh", "ja", "es"]);
    let language = supportedLanguages.has(window.CLOUD_LANGUAGE) ? window.CLOUD_LANGUAGE : (localStorage.getItem("cloudchattingLanguage") || "ko");
    if (!supportedLanguages.has(language)) language = "ko";

    const dictionaries = {
        en: {
            "화면": "Display", "다크 모드": "Dark mode", "라이트 모드": "Light mode", "오피스 모드 켜기": "Enable office mode", "오피스 모드 끄기": "Disable office mode",
            "편하게 보기": "Comfort view", "화면 대비": "Contrast", "편안함": "Comfort", "기본": "Default", "고대비": "High contrast", "글자 크기": "Text size", "작게": "Small", "크게": "Large", "채팅 밀도": "Chat density", "여유롭게": "Spacious", "촘촘하게": "Compact", "움직임 줄이기": "Reduce motion",
            "계정 · 알림": "Account & notifications", "계정 설정": "Account settings", "알림 설정": "Notifications", "지원": "Support", "공지사항 · 도움말": "Notices & help", "사용자 리뷰": "User reviews", "로그아웃": "Log out", "언어": "Language",
            "채팅방": "Chats", "친구 추가": "Add friend", "친구 찾기": "Find friends", "메시지함": "Inbox", "받은 요청": "Received", "보낸 요청": "Sent", "아직 채팅방 없어요": "No chats yet", "대화를 선택하세요": "Select a conversation", "아직 열린 대화가 없어요": "No conversation open", "메시지를 입력하세요": "Type a message",
            "채팅방 테마": "Chat theme", "기본 테마": "Basic themes", "계절 테마": "Seasonal themes", "시즌 테마": "Event themes", "봄": "Spring", "여름": "Summer", "가을": "Autumn", "겨울": "Winter", "크리스마스": "Christmas", "할로윈": "Halloween",
            "로그인": "Log in", "회원가입": "Sign up", "아이디 또는 이메일": "Username or email", "이메일": "Email", "아이디": "Username", "인증번호": "Verification code", "인증번호 받기": "Send code", "인증하기": "Verify", "비밀번호": "Password", "로그인 정보 저장": "Remember me", "비밀번호 표시": "Show password", "아이디 찾기": "Find username", "비밀번호 찾기": "Find password", "비밀번호 재설정": "Reset password", "비밀번호 변경": "Change password",
            "프로필 편집": "Edit profile", "표시 이름": "Display name", "소개글": "Bio", "프로필 공개 범위": "Profile visibility", "전체 공개": "Public", "친구 공개": "Friends only", "비공개": "Private", "저장하기": "Save", "취소": "Cancel", "사진 변경": "Change photo", "배경 변경": "Change cover", "배경사진 제거": "Remove cover",
            "사진": "Photo", "동영상": "Video", "파일": "File", "음성": "Voice", "답장": "Reply", "수정": "Edit", "복사": "Copy", "고정": "Pin", "전달": "Forward", "삭제": "Delete", "신고": "Report",
            "메시지를 복사했습니다.": "Message copied.", "메시지를 수정했습니다.": "Message updated.", "메시지를 전달했습니다.": "Message forwarded.", "신고가 접수되었습니다.": "Report submitted.", "사진을 보냈습니다.": "Photo sent.", "파일을 보냈습니다.": "File sent.", "친구 요청을 보냈습니다.": "Friend request sent.", "서버와 통신 중 문제가 발생했습니다.": "A server communication error occurred.", "먼저 채팅방을 선택해주세요.": "Select a chat first.", "이름을 입력해주세요.": "Enter a name.", "이메일을 입력해주세요.": "Enter an email.", "인증번호 인증을 먼저 완료해주세요.": "Complete verification first.", "인증 코드를 이메일로 전송했습니다.": "Verification code sent by email.", "이 브라우저는 알림을 지원하지 않습니다.": "This browser does not support notifications.", "브라우저 알림을 켰습니다.": "Browser notifications enabled."
        },
        zh: {
            "화면": "显示", "다크 모드": "深色模式", "라이트 모드": "浅色模式", "오피스 모드 켜기": "开启办公模式", "오피스 모드 끄기": "关闭办公模式", "편하게 보기": "舒适查看", "화면 대비": "对比度", "편안함": "舒适", "기본": "默认", "고대비": "高对比度", "글자 크기": "字体大小", "작게": "小", "크게": "大", "채팅 밀도": "聊天密度", "여유롭게": "宽松", "촘촘하게": "紧凑", "움직임 줄이기": "减少动画",
            "계정 · 알림": "账户和通知", "계정 설정": "账户设置", "알림 설정": "通知设置", "지원": "支持", "공지사항 · 도움말": "公告和帮助", "사용자 리뷰": "用户评价", "로그아웃": "退出登录", "언어": "语言", "채팅방": "聊天", "친구 추가": "添加好友", "친구 찾기": "查找好友", "메시지함": "收件箱", "받은 요청": "收到的请求", "보낸 요청": "已发送请求", "아직 채팅방 없어요": "还没有聊天", "대화를 선택하세요": "请选择对话", "아직 열린 대화가 없어요": "没有打开的对话", "메시지를 입력하세요": "输入消息",
            "채팅방 테마": "聊天主题", "기본 테마": "基础主题", "계절 테마": "季节主题", "시즌 테마": "节日主题", "봄": "春季", "여름": "夏季", "가을": "秋季", "겨울": "冬季", "크리스마스": "圣诞节", "할로윈": "万圣节", "로그인": "登录", "회원가입": "注册", "아이디 또는 이메일": "用户名或邮箱", "이메일": "邮箱", "아이디": "用户名", "인증번호": "验证码", "인증번호 받기": "获取验证码", "인증하기": "验证", "비밀번호": "密码", "로그인 정보 저장": "记住登录信息", "비밀번호 표시": "显示密码", "아이디 찾기": "找回用户名", "비밀번호 찾기": "找回密码", "비밀번호 재설정": "重置密码", "비밀번호 변경": "修改密码",
            "프로필 편집": "编辑资料", "표시 이름": "显示名称", "소개글": "简介", "프로필 공개 범위": "资料可见范围", "전체 공개": "公开", "친구 공개": "仅好友", "비공개": "私密", "저장하기": "保存", "취소": "取消", "사진 변경": "更换照片", "배경 변경": "更换封面", "배경사진 제거": "移除封面", "사진": "照片", "동영상": "视频", "파일": "文件", "음성": "语音", "답장": "回复", "수정": "编辑", "복사": "复制", "고정": "置顶", "전달": "转发", "삭제": "删除", "신고": "举报"
        },
        ja: {
            "화면": "表示", "다크 모드": "ダークモード", "라이트 모드": "ライトモード", "오피스 모드 켜기": "オフィスモードをオン", "오피스 모드 끄기": "オフィスモードをオフ", "편하게 보기": "見やすく表示", "화면 대비": "コントラスト", "편안함": "見やすい", "기본": "基本", "고대비": "高コントラスト", "글자 크기": "文字サイズ", "작게": "小", "크게": "大", "채팅 밀도": "チャット密度", "여유롭게": "ゆったり", "촘촘하게": "コンパクト", "움직임 줄이기": "動きを減らす",
            "계정 · 알림": "アカウント・通知", "계정 설정": "アカウント設定", "알림 설정": "通知設定", "지원": "サポート", "공지사항 · 도움말": "お知らせ・ヘルプ", "사용자 리뷰": "ユーザーレビュー", "로그아웃": "ログアウト", "언어": "言語", "채팅방": "チャット", "친구 추가": "友だち追加", "친구 찾기": "友だちを探す", "메시지함": "受信箱", "받은 요청": "受信リクエスト", "보낸 요청": "送信リクエスト", "아직 채팅방 없어요": "チャットはまだありません", "대화를 선택하세요": "会話を選択してください", "아직 열린 대화가 없어요": "開いている会話はありません", "메시지를 입력하세요": "メッセージを入力",
            "채팅방 테마": "チャットテーマ", "기본 테마": "基本テーマ", "계절 테마": "季節テーマ", "시즌 테마": "イベントテーマ", "봄": "春", "여름": "夏", "가을": "秋", "겨울": "冬", "크리스마스": "クリスマス", "할로윈": "ハロウィン", "로그인": "ログイン", "회원가입": "新規登録", "아이디 또는 이메일": "ユーザー名またはメール", "이메일": "メール", "아이디": "ユーザー名", "인증번호": "認証コード", "인증번호 받기": "コードを送信", "인증하기": "認証", "비밀번호": "パスワード", "로그인 정보 저장": "ログイン情報を保存", "비밀번호 표시": "パスワードを表示", "아이디 찾기": "IDを探す", "비밀번호 찾기": "パスワードを探す", "비밀번호 재설정": "パスワード再設定", "비밀번호 변경": "パスワード変更",
            "프로필 편집": "プロフィール編集", "표시 이름": "表示名", "소개글": "自己紹介", "프로필 공개 범위": "公開範囲", "전체 공개": "公開", "친구 공개": "友だちのみ", "비공개": "非公開", "저장하기": "保存", "취소": "キャンセル", "사진 변경": "写真を変更", "배경 변경": "背景を変更", "배경사진 제거": "背景を削除", "사진": "写真", "동영상": "動画", "파일": "ファイル", "음성": "音声", "답장": "返信", "수정": "編集", "복사": "コピー", "고정": "固定", "전달": "転送", "삭제": "削除", "신고": "報告"
        },
        es: {
            "화면": "Pantalla", "다크 모드": "Modo oscuro", "라이트 모드": "Modo claro", "오피스 모드 켜기": "Activar modo oficina", "오피스 모드 끄기": "Desactivar modo oficina", "편하게 보기": "Vista cómoda", "화면 대비": "Contraste", "편안함": "Cómodo", "기본": "Predeterminado", "고대비": "Alto contraste", "글자 크기": "Tamaño de texto", "작게": "Pequeño", "크게": "Grande", "채팅 밀도": "Densidad del chat", "여유롭게": "Espacioso", "촘촘하게": "Compacto", "움직임 줄이기": "Reducir movimiento",
            "계정 · 알림": "Cuenta y notificaciones", "계정 설정": "Configuración de cuenta", "알림 설정": "Notificaciones", "지원": "Soporte", "공지사항 · 도움말": "Avisos y ayuda", "사용자 리뷰": "Reseñas", "로그아웃": "Cerrar sesión", "언어": "Idioma", "채팅방": "Chats", "친구 추가": "Añadir amigo", "친구 찾기": "Buscar amigos", "메시지함": "Bandeja de entrada", "받은 요청": "Solicitudes recibidas", "보낸 요청": "Solicitudes enviadas", "아직 채팅방 없어요": "Aún no hay chats", "대화를 선택하세요": "Selecciona una conversación", "아직 열린 대화가 없어요": "No hay conversación abierta", "메시지를 입력하세요": "Escribe un mensaje",
            "채팅방 테마": "Tema del chat", "기본 테마": "Temas básicos", "계절 테마": "Temas estacionales", "시즌 테마": "Temas de evento", "봄": "Primavera", "여름": "Verano", "가을": "Otoño", "겨울": "Invierno", "크리스마스": "Navidad", "할로윈": "Halloween", "로그인": "Iniciar sesión", "회원가입": "Registrarse", "아이디 또는 이메일": "Usuario o correo", "이메일": "Correo electrónico", "아이디": "Usuario", "인증번호": "Código de verificación", "인증번호 받기": "Enviar código", "인증하기": "Verificar", "비밀번호": "Contraseña", "로그인 정보 저장": "Recordar inicio", "비밀번호 표시": "Mostrar contraseña", "아이디 찾기": "Buscar usuario", "비밀번호 찾기": "Buscar contraseña", "비밀번호 재설정": "Restablecer contraseña", "비밀번호 변경": "Cambiar contraseña",
            "프로필 편집": "Editar perfil", "표시 이름": "Nombre visible", "소개글": "Biografía", "프로필 공개 범위": "Visibilidad del perfil", "전체 공개": "Público", "친구 공개": "Solo amigos", "비공개": "Privado", "저장하기": "Guardar", "취소": "Cancelar", "사진 변경": "Cambiar foto", "배경 변경": "Cambiar portada", "배경사진 제거": "Quitar portada", "사진": "Foto", "동영상": "Vídeo", "파일": "Archivo", "음성": "Voz", "답장": "Responder", "수정": "Editar", "복사": "Copiar", "고정": "Fijar", "전달": "Reenviar", "삭제": "Eliminar", "신고": "Denunciar"
        }
    };

    // 화면을 만들면서 추가된 짧은 안내·확인 문구도 이 목록에 모아, 언어를 바꾼 뒤 일부만 한국어로 남지 않게 한다.
    Object.assign(dictionaries.en, {
        "계정이 없으신가요?": "Don't have an account?", "이미 계정이 있으신가요?": "Already have an account?", "그룹 사진을 삭제하시겠습니까?": "Remove the group photo?", "그룹 채팅을 종료할까요? 이전 대화는 남지만 새 메시지는 보낼 수 없습니다.": "End this group chat? Previous messages remain, but new messages cannot be sent.", "로그아웃 하시겠습니까?": "Log out?", "메시지를 삭제 하시겠습니까?": "Delete this message?", "채팅방을 삭제 하시겠습니까?": "Delete this chat?", "이 문의 내역을 삭제할까요?": "Delete this inquiry?", "프로필 사진을 삭제하시겠습니까?": "Remove the profile photo?", "정말 이 그룹에서 나가시겠습니까? 다시 들어오려면 초대를 받아야 합니다.": "Leave this group? You will need an invitation to rejoin.", "정말로 계정을 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.": "Delete your account? This cannot be undone.", "리뷰를 삭제할까요?": "Delete this review?", "이 공지를 삭제할까요?": "Delete this notice?", "이 신고 내역을 삭제할까요? 삭제한 신고는 복구할 수 없습니다.": "Delete this report? Deleted reports cannot be restored.", "이 계정의 이용 제한을 해제할까요?": "Lift this account restriction?", "사진 공유": "Share photo", "고정 메시지": "Pinned message", "사진 모아보기": "Media gallery", "채팅방 고정": "Pin chat", "알림 끄기": "Mute notifications", "그룹 관리": "Manage group"
    });
    Object.assign(dictionaries.zh, {
        "계정이 없으신가요?": "还没有账户？", "이미 계정이 있으신가요?": "已有账户？", "그룹 사진을 삭제하시겠습니까?": "要删除群组照片吗？", "그룹 채팅을 종료할까요? 이전 대화는 남지만 새 메시지는 보낼 수 없습니다.": "要结束群聊吗？历史消息会保留，但不能发送新消息。", "로그아웃 하시겠습니까?": "要退出登录吗？", "메시지를 삭제 하시겠습니까?": "要删除这条消息吗？", "채팅방을 삭제 하시겠습니까?": "要删除此聊天吗？", "이 문의 내역을 삭제할까요?": "要删除此咨询记录吗？", "프로필 사진을 삭제하시겠습니까?": "要删除头像吗？", "정말 이 그룹에서 나가시겠습니까? 다시 들어오려면 초대를 받아야 합니다.": "要离开此群组吗？重新加入需要邀请。", "정말로 계정을 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.": "要删除账户吗？此操作无法撤销。", "리뷰를 삭제할까요?": "要删除这条评价吗？", "이 공지를 삭제할까요?": "要删除此公告吗？", "이 신고 내역을 삭제할까요? 삭제한 신고는 복구할 수 없습니다.": "要删除此举报记录吗？删除后无法恢复。", "이 계정의 이용 제한을 해제할까요?": "要解除该账户的限制吗？", "사진 공유": "分享照片", "고정 메시지": "置顶消息", "사진 모아보기": "媒体库", "채팅방 고정": "置顶聊天", "알림 끄기": "关闭通知", "그룹 관리": "管理群组"
    });
    Object.assign(dictionaries.ja, {
        "계정이 없으신가요?": "アカウントをお持ちでないですか？", "이미 계정이 있으신가요?": "すでにアカウントをお持ちですか？", "그룹 사진을 삭제하시겠습니까?": "グループ写真を削除しますか？", "그룹 채팅을 종료할까요? 이전 대화는 남지만 새 메시지는 보낼 수 없습니다.": "グループチャットを終了しますか？履歴は残りますが、新しいメッセージは送れません。", "로그아웃 하시겠습니까?": "ログアウトしますか？", "메시지를 삭제 하시겠습니까?": "このメッセージを削除しますか？", "채팅방을 삭제 하시겠습니까?": "このチャットを削除しますか？", "이 문의 내역을 삭제할까요?": "このお問い合わせ履歴を削除しますか？", "프로필 사진을 삭제하시겠습니까?": "プロフィール写真を削除しますか？", "정말 이 그룹에서 나가시겠습니까? 다시 들어오려면 초대를 받아야 합니다.": "このグループから退出しますか？再参加には招待が必要です。", "정말로 계정을 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.": "アカウントを削除しますか？この操作は元に戻せません。", "리뷰를 삭제할까요?": "このレビューを削除しますか？", "이 공지를 삭제할까요?": "このお知らせを削除しますか？", "이 신고 내역을 삭제할까요? 삭제한 신고는 복구할 수 없습니다.": "この報告を削除しますか？削除した報告は復元できません。", "이 계정의 이용 제한을 해제할까요?": "このアカウントの利用制限を解除しますか？", "사진 공유": "写真を共有", "고정 메시지": "固定メッセージ", "사진 모아보기": "メディア一覧", "채팅방 고정": "チャットを固定", "알림 끄기": "通知をオフ", "그룹 관리": "グループ管理"
    });
    Object.assign(dictionaries.es, {
        "계정이 없으신가요?": "¿No tienes cuenta?", "이미 계정이 있으신가요?": "¿Ya tienes una cuenta?", "그룹 사진을 삭제하시겠습니까?": "¿Eliminar la foto del grupo?", "그룹 채팅을 종료할까요? 이전 대화는 남지만 새 메시지는 보낼 수 없습니다.": "¿Cerrar este grupo? Los mensajes anteriores se conservarán, pero no se podrán enviar nuevos.", "로그아웃 하시겠습니까?": "¿Cerrar sesión?", "메시지를 삭제 하시겠습니까?": "¿Eliminar este mensaje?", "채팅방을 삭제 하시겠습니까?": "¿Eliminar este chat?", "이 문의 내역을 삭제할까요?": "¿Eliminar esta consulta?", "프로필 사진을 삭제하시겠습니까?": "¿Eliminar la foto de perfil?", "정말 이 그룹에서 나가시겠습니까? 다시 들어오려면 초대를 받아야 합니다.": "¿Salir de este grupo? Necesitarás una invitación para volver.", "정말로 계정을 삭제하시겠습니까? 이 작업은 되돌릴 수 없습니다.": "¿Eliminar tu cuenta? Esta acción no se puede deshacer.", "리뷰를 삭제할까요?": "¿Eliminar esta reseña?", "이 공지를 삭제할까요?": "¿Eliminar este aviso?", "이 신고 내역을 삭제할까요? 삭제한 신고는 복구할 수 없습니다.": "¿Eliminar este reporte? No se puede restaurar.", "이 계정의 이용 제한을 해제할까요?": "¿Quitar la restricción de esta cuenta?", "사진 공유": "Compartir foto", "고정 메시지": "Mensaje fijado", "사진 모아보기": "Galería multimedia", "채팅방 고정": "Fijar chat", "알림 끄기": "Silenciar notificaciones", "그룹 관리": "Administrar grupo"
    });

    // 테마 이름과 설명은 버튼을 열었을 때 처음 보이는 문구라 별도 묶음으로 관리한다.
    Object.assign(dictionaries.en, {
        "하트": "Heart", "감성 핑크": "Soft pink", "테디베어": "Teddy bear", "포근한 베이지": "Warm beige",
        "글라스": "Glass", "맑은 유리 질감": "Clear glass texture", "오로라": "Aurora", "은은한 북극빛": "Soft polar glow",
        "모노": "Mono", "차분한 모노톤": "Calm monotone", "특별한 시즌에 어울리는 한정 분위기의 테마예요.": "Limited themes for special seasons."
    });
    Object.assign(dictionaries.zh, {
        "하트": "爱心", "감성 핑크": "柔和粉色", "테디베어": "泰迪熊", "포근한 베이지": "温暖米色",
        "글라스": "玻璃", "맑은 유리 질감": "通透玻璃质感", "오로라": "极光", "은은한 북극빛": "柔和极光",
        "모노": "单色", "차분한 모노톤": "沉静单色调", "특별한 시즌에 어울리는 한정 분위기의 테마예요.": "适合特别季节的限定主题。"
    });
    Object.assign(dictionaries.ja, {
        "하트": "ハート", "감성 핑크": "やさしいピンク", "테디베어": "テディベア", "포근한 베이지": "あたたかいベージュ",
        "글라스": "グラス", "맑은 유리 질감": "透明なガラスの質感", "오로라": "オーロラ", "은은한 북극빛": "やわらかな極光",
        "모노": "モノ", "차분한 모노톤": "落ち着いたモノトーン", "특별한 시즌에 어울리는 한정 분위기의 테마예요.": "特別な季節に合う限定テーマです。"
    });
    Object.assign(dictionaries.es, {
        "하트": "Corazón", "감성 핑크": "Rosa suave", "테디베어": "Oso de peluche", "포근한 베이지": "Beige cálido",
        "글라스": "Cristal", "맑은 유리 질감": "Textura de cristal claro", "오로라": "Aurora", "은은한 북극빛": "Suave luz polar",
        "모노": "Mono", "차분한 모노톤": "Monocromo sereno", "특별한 시즌에 어울리는 한정 분위기의 테마예요.": "Temas limitados para temporadas especiales."
    });

    function t(key) {
        const text = String(key || "").trim();
        return (dictionaries[language] && dictionaries[language][text]) || text;
    }

    function shouldSkip(node) {
        return node.closest && node.closest("script, style, pre, code, .messages-wrap, .bubble, .message-left, .chat-audio, [data-no-i18n]");
    }

    function translateTextNodes(root) {
        const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
        const nodes = [];
        while (walker.nextNode()) nodes.push(walker.currentNode);
        nodes.forEach(function (node) {
            if (!node.nodeValue.trim() || shouldSkip(node.parentElement)) return;
            const parent = node.parentElement;
            const original = parent.dataset.i18nText || node.nodeValue.trim();
            if (!dictionaries.en[original]) return;
            parent.dataset.i18nText = original;
            const localized = t(original);
            if (node.nodeValue.trim() !== localized) node.nodeValue = node.nodeValue.replace(node.nodeValue.trim(), localized);
        });
    }

    function translateAttributes(root) {
        root.querySelectorAll("[placeholder], [title], [aria-label]").forEach(function (element) {
            if (shouldSkip(element)) return;
            ["placeholder", "title", "aria-label"].forEach(function (attribute) {
                const dataKey = `i18n${attribute.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase())}`;
                const original = element.dataset[dataKey] || element.getAttribute(attribute);
                if (!original || !dictionaries.en[original]) return;
                element.dataset[dataKey] = original;
                element.setAttribute(attribute, t(original));
            });
        });
    }

    function translatePage(root = document.body) {
        if (!root) return;
        document.documentElement.lang = language;
        root.querySelectorAll("[data-language-select]").forEach(select => { select.value = language; });
        translateTextNodes(root);
        translateAttributes(root);
    }

    function setLanguage(nextLanguage, persist = true) {
        language = supportedLanguages.has(nextLanguage) ? nextLanguage : "ko";
        if (persist) localStorage.setItem("cloudchattingLanguage", language);
        document.querySelectorAll("[data-language-select]").forEach(select => { select.value = language; });
        translatePage();
        window.dispatchEvent(new CustomEvent("cloud-language-change", { detail: { language } }));
    }

    // 이후의 API 요청에도 현재 언어를 실어 보내 이메일·서버 안내 문구가 같은 언어를 따르게 한다.
    const originalFetch = window.fetch;
    window.fetch = function (resource, options = {}) {
        const headers = new Headers(options.headers || (resource instanceof Request ? resource.headers : undefined));
        headers.set("X-App-Language", language);
        return originalFetch(resource, { ...options, headers });
    };

    document.addEventListener("change", function (event) {
        if (event.target.matches("[data-language-select]")) setLanguage(event.target.value);
    });

    window.CloudI18n = { t, setLanguage, translatePage, getLanguage: () => language, supportedLanguages: [...supportedLanguages] };
    function startTranslation() {
        translatePage();
        // 채팅 목록·모달처럼 JavaScript가 나중에 그리는 UI도 같은 번역 사전을 통과시킨다.
        // 새로 생긴 영역만 다음 화면 프레임에 번역한다. 메시지가 추가될 때마다 전체 페이지를
        // 다시 훑지 않아 채팅 중 화면이 무거워지지 않도록 한다.
        let translationQueued = false;
        const pendingRoots = new Set();
        const observer = new MutationObserver((mutations) => {
            mutations.forEach((mutation) => {
                mutation.addedNodes.forEach((node) => {
                    if (node.nodeType === Node.ELEMENT_NODE) pendingRoots.add(node);
                    else if (node.nodeType === Node.TEXT_NODE && node.parentElement) pendingRoots.add(node.parentElement);
                });
            });
            if (!pendingRoots.size || translationQueued) return;
            translationQueued = true;
            window.requestAnimationFrame(() => {
                pendingRoots.forEach((root) => translatePage(root));
                pendingRoots.clear();
                translationQueued = false;
            });
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }
    if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", startTranslation);
    else startTranslation();
}());
