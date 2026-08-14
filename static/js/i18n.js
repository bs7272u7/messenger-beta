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

    // 도움말·알림·리뷰처럼 모달을 연 뒤에 보이는 세부 안내도 빠짐없이 같은 사전에서 찾는다.
    // 다른 언어에 아직 개별 번역이 없는 새 문구는 영어를 안전한 공통 표현으로 사용한다.
    Object.assign(dictionaries.en, {
        "현재 대화": "Current conversation", "친구를 추가하거나 채팅방을 선택해보세요.": "Add a friend or select a chat room.",
        "친구를 추가하고 대화를 시작해보세요!": "Add a friend and start a conversation!", "아직 대화가 없어요. 메시지를 보내보세요!": "No messages yet. Send a message!",
        "대화를 선택해 시작하세요": "Select a conversation to get started", "채팅방 목록": "Chat list", "친구 관리": "Friend management",
        "모바일 메뉴": "Mobile menu", "채팅": "Chats", "친구": "Friends", "프로필": "Profile", "설정": "Settings",
        "상대방 아이디 입력": "Enter username", "아이디로 프로필 찾기": "Find profile by username", "새 그룹 만들기": "Create group", "친구 목록": "Friend list",
        "그룹 이름": "Group name", "함께할 친구 선택(2명 이상)": "Select friends (2 or more)", "만들기": "Create", "그룹 설정": "Group settings",
        "사진 삭제": "Remove photo", "멤버 초대": "Invite members", "그룹 채팅 종료": "End group chat", "그룹 나가기": "Leave group", "초대": "Invite",
        "새 메시지 알림": "New message notifications", "친구 요청 알림": "Friend request notifications", "그룹 초대 알림": "Group invite notifications", "브라우저 알림": "Browser notifications",
        "업데이트 사항": "Updates", "최근 10개": "Latest 10", "업데이트 내역을 불러오는 중입니다.": "Loading update history...", "이전 업데이트 사항": "Previous updates",
        "Cloud Chatting에 반영된 전체 업데이트 기록입니다.": "Full update history for Cloud Chatting.", "이전 업데이트 사항 닫기": "Close previous updates",
        "공지사항": "Notices", "공지사항을 불러오는 중입니다.": "Loading notices...", "도움말": "Help", "불편한 점이나 개선 의견을 남겨주시면 이메일로 직접 전달됩니다.": "Send us feedback or an issue and it will be delivered by email.",
        "계정 복구": "Account recovery", "로그인 중에도 아이디 안내와 비밀번호 재설정을 이용할 수 있습니다.": "You can find your username or reset your password here.",
        "가입 이메일 주소": "Registration email address", "아이디 안내 메일 보내기": "Send username reminder", "인증번호 6자리": "6-digit verification code",
        "새 비밀번호 (소문자·숫자·특수문자 포함 7자 이상)": "New password (7+ lowercase letters, numbers, symbols)",
        "문의 보내기": "Contact support", "문의 내용은 10자 이상 작성해주세요. 사진 또는 동영상은 선택 사항입니다.": "Please write at least 10 characters. Photos and videos are optional.",
        "어떤 점이 불편했는지 자세히 알려주세요.": "Tell us in detail what was inconvenient.", "사진 · 동영상 첨부": "Attach photo or video", "선택": "Optional", "첨부 파일 없음": "No file attached", "문의 전송하기": "Send inquiry",
        "내 문의 내역": "My inquiries", "답변을 확인하고, 답변 전 문의는 수정하거나 삭제할 수 있습니다.": "View replies and edit or delete inquiries before a reply arrives.",
        "문의 내역을 불러오는 중입니다.": "Loading inquiry history...", "운영 안내": "Service notices", "운영팀에서 전달한 경고 및 이용 관련 안내를 확인할 수 있습니다.": "View warnings and service notices from the moderation team.",
        "운영 안내를 불러오는 중입니다.": "Loading service notices...", "테디베어 아이콘:": "Teddy bear icon:", "이용약관": "Terms of service", "개인정보처리방침": "Privacy policy",
        "Cloud Chatting을 사용하며 느낀 점을 남겨주세요.": "Share your experience using Cloud Chatting.", "리뷰 작성": "Write a review", "별점 선택": "Select rating",
        "★★★★★ 아주 좋아요": "★★★★★ Excellent", "★★★★ 좋아요": "★★★★ Good", "★★★ 보통이에요": "★★★ Average", "★★ 아쉬워요": "★★ Needs improvement", "★ 불편해요": "★ Poor",
        "후기 5자 이상": "Review (5+ characters)", "리뷰 등록": "Submit review", "모든 리뷰": "All reviews", "관리자 답변을 확인할 수 있어요.": "You can view administrator replies.",
        "첫 번째 리뷰를 남겨주세요.": "Be the first to leave a review.", "음성메시지 버튼 누르고 한번 더 누르면 전송됨": "Press the voice button again to send.",
        "아직 주고받은 사진이 없습니다.": "No shared photos yet.", "사진": "Photo", "파일": "File", "음성 메시지": "Voice message", "첨부 파일": "Attachment",
        "수정 됨": "Edited", "채팅방 안내": "Chat notice", "고정 해제": "Unpin", "알림 켜기": "Turn on notifications", "알림 끄기": "Mute notifications",
        "현재 온라인입니다.": "Currently online.", "현재 오프라인입니다.": "Currently offline.", "소개글이 없습니다.": "No bio provided.", "온라인": "Online", "오프라인": "Offline",
        "종료된 그룹 채팅방입니다. 이전 대화만 확인할 수 있습니다.": "This group chat has ended. You can view previous messages only.",
        "종료된 그룹 채팅입니다. 이전 대화만 볼 수 있습니다.": "This group chat has ended. You can view previous messages only.", "차단된 사용자입니다": "Blocked user",
        "차단된 사용자와는 메시지를 주고받을 수 없습니다.": "You cannot exchange messages with a blocked user.",
        "메시지를 수정하지 못했습니다.": "Could not edit the message.", "메시지를 보내지 못했습니다.": "Could not send the message.", "사진을 보내지 못했습니다.": "Could not send the photo.",
        "파일을 보내지 못했습니다.": "Could not send the file.", "이 브라우저에서는 음성 메시지를 지원하지 않습니다.": "This browser does not support voice messages.",
        "녹음 중입니다. 다시 누르면 전송합니다. (최대 30초)": "Recording. Press again to send (max 30 seconds).", "마이크 권한을 허용해주세요.": "Please allow microphone access.",
        "아직 채팅방 없어요": "No chats yet", "아직 대화가 없습니다.": "No conversation yet.", "개의 채팅방": " chat rooms", "고정된 채팅방": "Pinned chat", "알림 꺼짐": "Notifications muted",
        "친구 요청을 보냈습니다.": "Friend request sent.", "보낸 친구 요청이 아직 없습니다.": "No sent friend requests.", "받은 요청이 없습니다.": "No received requests.", "요청 취소": "Cancel request", "방장": "Owner", "나": "Me",
        "초대할 수 있는 친구가 없습니다.": "There are no friends to invite.", "초대할 친구를 선택해주세요.": "Select friends to invite.", "함께 그룹을 만들 친구가 없습니다.": "There are no friends available for a group.",
        "그룹 이름을 입력해주세요.": "Enter a group name.", "친구를 2명 이상 선택해주세요.": "Select at least two friends.", "검색 중...": "Searching...", "사용자를 찾을 수 없습니다.": "User not found.",
        "채팅방을 고정했습니다.": "Chat pinned.", "채팅방 고정을 해제했습니다.": "Chat unpinned.", "이 채팅방 알림을 껐습니다.": "Chat notifications muted.", "이 채팅방 알림을 켰습니다.": "Chat notifications enabled.",
        "테마 변경에 실패했습니다.": "Could not change the theme.", "이름을 입력해주세요.": "Enter a name.", "프로필 정보를 저장하지 못했습니다.": "Could not save profile information.",
        "배경사진을 변경했습니다.": "Cover photo changed.", "배경사진을 제거했습니다.": "Cover photo removed.", "배경사진 없음": "No cover photo", "이미지 파일만 첨부할 수 있습니다.": "Only image files can be attached.",
        "업데이트 내역 없음": "No update history", "최근 업데이트 내역이 없습니다.": "No recent updates.", "업데이트 내역을 불러오지 못했습니다.": "Could not load update history.",
        "이전 업데이트 내역을 불러오는 중입니다.": "Loading previous updates...", "이전 업데이트 내역 없음": "No previous update history", "표시할 이전 업데이트 내역이 없습니다.": "No previous updates to display.", "이전 업데이트 내역을 불러오지 못했습니다.": "Could not load previous updates.",
        "첨부파일은 10MB 이하만 보낼 수 있습니다.": "Attachments must be 10 MB or smaller.", "문의 내용은 10자 이상 입력해주세요.": "Please enter at least 10 characters.", "전송 중...": "Sending...", "문의 전송에 실패했습니다.": "Could not send inquiry.",
        "답변 대기": "Waiting for reply", "답변 완료": "Reply completed", "처리 완료": "Resolved", "첨부 파일 보기": "View attachment", "관리자 답변": "Administrator reply", "보낸 문의가 없습니다.": "No inquiries sent.", "문의 내역을 불러오지 못했습니다.": "Could not load inquiry history.",
        "운영 정책 위반": "Violation of service policy", "처리 일시 ·": "Processed ·", "확인했습니다": "I understand", "운영 경고": "Service warning", "받은 운영 안내가 없습니다.": "No service notices received.",
        "경고 확인 처리에 실패했습니다.": "Could not acknowledge warning.", "문의 내용을 수정하세요.": "Edit your inquiry.", "수정에 실패했습니다.": "Could not edit.", "문의 내용을 수정했습니다.": "Inquiry updated.", "삭제에 실패했습니다.": "Could not delete.", "문의 내역을 삭제했습니다.": "Inquiry deleted.",
        "만료됨": "Expired", "가입 이메일 주소를 입력해주세요.": "Enter your registration email address.", "아이디 안내 이메일 전송에 실패했습니다.": "Could not send username reminder email.", "인증번호 이메일 전송에 실패했습니다.": "Could not send verification email.",
        "인증번호를 보냈습니다.": "Verification code sent.", "인증번호가 만료되었습니다. 다시 요청해주세요.": "Verification code expired. Request a new one.", "이메일과 인증번호 6자리를 입력해주세요.": "Enter your email and 6-digit verification code.",
        "인증번호 인증을 먼저 완료해주세요.": "Complete verification first.", "비밀번호 변경에 실패했습니다.": "Could not change password.", "비밀번호가 변경되었습니다.": "Password changed.", "변경 중...": "Changing...",
        "현재 등록된 공지사항이 없습니다.": "There are no notices.", "공지사항을 불러오지 못했습니다.": "Could not load notices.", "리뷰 등록에 실패했습니다.": "Could not submit review.", "리뷰를 등록했습니다.": "Review submitted.",
        "아이디가 변경되었습니다.": "Username changed.", "인증번호를 이메일로 보냈습니다.": "Verification code sent by email.", "발송 중...": "Sending...", "확인 중...": "Checking...", "인증 완료": "Verified", "✓ 이메일 인증이 완료되었습니다.": "✓ Email verification completed."
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

    // 기본 화면 밖의 상세 메뉴와 모달에 쓰이는 문구다. 새 화면도 같은 키를 재사용한다.
    Object.assign(dictionaries.en, {
        "채팅방 목록으로 돌아가기": "Back to chat list", "채팅방 더보기": "More chat options", "채팅 정보": "Chat information",
        "사진 모아보기": "Media gallery", "메시지 검색...": "Search messages...", "메시지 전달": "Forward message", "전달할 채팅방을 선택해주세요.": "Select a chat to forward to.", "전달하기": "Forward",
        "메시지 신고": "Report message", "신고 내용은 관리자만 확인하며, 상대방에게 신고자 정보가 전달되지 않습니다.": "Only administrators can see this report. The other person will not see reporter information.",
        "신고 사유 선택": "Select a reason", "스팸": "Spam", "욕설·괴롭힘": "Abuse or harassment", "부적절한 콘텐츠": "Inappropriate content", "사칭": "Impersonation", "기타": "Other", "추가 설명 (선택)": "Additional details (optional)", "신고 접수하기": "Submit report",
        "답장": "Reply", "메시지 수정": "Edit message", "메시지 검색": "Search messages", "사진 확대": "Zoom photo", "사진 조절 닫기": "Close photo editor", "사진을 드래그해 위치를 옮기고, 슬라이더로 확대할 수 있어요.": "Drag the photo to reposition it and use the slider to zoom.", "적용하기": "Apply",
        "계절의 색감을 담은 차분한 채팅 배경이에요.": "Calm chat backgrounds inspired by seasonal colors.", "깔끔한 블루": "Clean blue", "계절 추천": "Season pick", "벚꽃 · 새싹 그린": "Cherry blossom · fresh green", "맑은 하늘 · 아쿠아": "Clear sky · aqua", "앰버 · 단풍 브라운": "Amber · autumn brown", "아이스 블루 · 실버": "Ice blue · silver", "시즌 추천": "Season pick", "딥 네이비 · 골드 포인트": "Deep navy · gold", "먹색 · 보라 · 오렌지": "Black · purple · orange", "크리스마스": "Christmas", "할로윈": "Halloween",
        "현재 이메일:": "Current email:", "등록된 이메일 없음": "No email registered", "새 이메일 주소": "New email address", "인증코드 받기": "Send verification code", "인증코드 6자리": "6-digit verification code", "현재 비밀번호": "Current password", "이메일 변경": "Change email", "아이디 변경": "Change username", "새 아이디 (소문자+숫자 5자 이상)": "New username (5+ lowercase letters and numbers)", "아이디 저장": "Save username", "새 비밀번호 (소문자+숫자+특수문자 7자 이상)": "New password (7+ lowercase letters, numbers, symbols)", "비밀번호 저장": "Save password", "계정 삭제": "Delete account", "계정 삭제하기": "Delete account",
        "운영 경고가 도착했습니다": "A service warning has arrived", "서비스 운영 정책 위반으로 경고가 기록되었습니다. 내용을 확인하고 안전한 이용을 부탁드립니다.": "A warning was recorded for a service policy violation. Please review it and use the service safely.", "처리 사유": "Reason", "CLOUD CHATTING 운영 안내": "CLOUD CHATTING Service notice",
        "친구 요청을 한 곳에서 관리하세요.": "Manage friend requests in one place.", "메시지함 닫기": "Close inbox", "받은 요청": "Received", "보낸 요청": "Sent", "다운로드": "Download", "확인": "Confirm", "업데이트": "Update",
        "프로필 편집 닫기": "Close profile editor", "프로필 배경사진 미리보기": "Profile cover preview", "배경 변경": "Change cover", "프로필 사진 변경": "Change profile photo", "표시 이름": "Display name", "이름": "Name", "최대 300자": "Up to 300 characters", "나를 간단히 소개해보세요.": "Introduce yourself briefly.", "프로필 사진 삭제": "Remove profile photo", "저장하기": "Save",
        "지원": "Support", "화면": "Display", "계정 · 알림": "Account · notifications", "친구 추가": "Add friend", "친구 찾기": "Find friends", "친구만 공개": "Friends only", "전체 공개": "Public", "비공개": "Private",
        "계정으로 로그인해서 대화를 이어가세요.": "Log in to your account and continue your conversations.", "이메일 인증 후 비밀번호를 정해주세요.": "Verify your email, then choose a password.", "가입하고 시작하기": "Sign up and start", "아이디 또는 이메일": "Username or email", "영문 소문자, 숫자, 특수문자 7자 이상": "7+ lowercase letters, numbers, and symbols",
        "인증번호를 입력한 뒤 이메일 인증을 완료해주세요.": "Enter the verification code and complete email verification.", "문제가 발생했습니다.": "Something went wrong.", "서버에 연결할 수 없습니다.": "Cannot connect to the server.", "발송에 실패했습니다.": "Could not send.", "재전송": "Resend",
        "인증번호가 변경되어 다시 인증이 필요합니다.": "The code changed. Please verify again.", "이메일이 변경되어 인증번호를 다시 받아야 합니다.": "The email changed. Request a new code.", "이메일과 인증번호를 먼저 입력해주세요.": "Enter your email and verification code first.", "인증에 실패했습니다.": "Verification failed.",
        "아이디 안내 이메일 전송에 실패했습니다.": "Could not send username reminder email.", "비밀번호가 변경되었습니다. 새 비밀번호로 로그인해주세요.": "Password changed. Please log in with your new password.", "인증번호와 새 비밀번호를 모두 입력해주세요.": "Enter both the verification code and new password.",
        "다국어 동적 문구 번역 보완": "Improved dynamic UI translations", "다국어 언어 설정 기능 추가": "Added multilingual language settings", "코드 구조 설명 주석 보강": "Expanded code structure comments", "계절 테마와 공감 색상 개선": "Improved seasonal themes and reaction colors", "편하게 보기 아코디언 메뉴 적용": "Added collapsible comfort view settings"
    });

    function t(key) {
        const text = String(key || "").trim();
        return (dictionaries[language] && dictionaries[language][text]) || dictionaries.en[text] || text;
    }

    function shouldSkip(node) {
        // 실제 사용자가 작성한 말풍선만 제외한다. 빈 대화 안내는 messages-wrap 안에 있어도 UI 문구이므로 번역한다.
        return node.closest && node.closest("script, style, pre, code, .bubble, .message-left, .chat-audio, [data-no-i18n]");
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
