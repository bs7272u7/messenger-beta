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
        "채팅 테마": "聊天主题", "↩️ 답장": "↩️ 回复", "채팅 테마 분류": "聊天主题分类", "프로필 사진 조절": "调整头像", "영문 소문자, 숫자 5자 이상": "至少 5 位小写字母和数字", "가입할 때 등록한 이메일을 입력하면 아이디 안내 메일을 보내드립니다.": "输入注册时使用的邮箱，我们将发送用户名提醒邮件。", "가입 이메일로 인증번호를 받은 뒤 새 비밀번호를 설정하세요.": "在注册邮箱接收验证码后设置新密码。", "새 비밀번호": "新密码",
        "관리자 페이지": "管理控制台", "서비스 운영과 사용자 요청을 관리하는 공간입니다.": "管理服务运营和用户请求。", "보안 운영 세션 활성화": "安全管理会话已启用", "메신저로 돌아가기": "返回聊天", "관리자 안내": "管理员说明", "관리자 권한이 확인되었습니다.": "管理员权限已验证。", "이 페이지는 서버에서 권한을 확인한 계정만 열 수 있습니다. 다음 단계에서 각 관리 메뉴를 연결합니다.": "只有经服务器授权的账户才能打开此页面。", "관리 메뉴": "管理工具", "공지사항 관리": "公告管理", "새 공지 작성과 게시 상태를 한곳에서 관리합니다.": "在一处创建公告并管理发布状态。", "작성 기능 연결됨": "发布功能已连接", "문의 내역": "咨询记录", "사용자가 보낸 문의와 첨부 파일을 확인하고 처리합니다.": "查看并处理用户咨询和附件。", "답변·상태 처리 연결됨": "回复和状态功能已连接", "신고 관리": "举报管理", "신고된 내용과 처리 결과를 안전하게 관리합니다.": "安全管理举报内容和处理结果。", "접수 내역 확인 가능": "可查看已提交举报", "공지사항 작성": "创建公告", "제목": "标题", "사용자에게 표시할 공지 제목": "向用户显示的公告标题", "내용": "内容", "공지 내용을 작성하세요.": "编写公告内容。", "바로 게시하기": "立即发布", "공지 등록": "发布公告", "최근 공지": "最近公告", "불러오는 중...": "加载中…", "신고 내역": "举报记录", "이용 제한 계정": "受限账户",
        "관리자 보안 확인": "管理员安全验证", "운영 콘솔에 들어가기 전, 재현님이 지정한 관리자 접근 키를 확인합니다. 인증은 30분 동안만 유지됩니다.": "进入管理控制台前，请验证设置的管理员访问密钥。验证有效期为 30 分钟。", "관리자 접근 키": "管理员访问密钥", "보안 확인 후 계속": "验证后继续", "접근 키 설정이 필요합니다.": "需要设置访问密钥。", "Render 환경변수에": "请在 Render 环境变量中添加", "를 추가한 뒤 다시 시도해주세요.": "后重试。", "로그인으로 돌아가기": "返回登录",
        "오피스 모드에서는 다크/라이트 모드를 변경할 수 없습니다.": "办公模式下无法切换深色或浅色模式。", "오피스 모드에서는 화면 모드 고정": "办公模式下显示模式已锁定", "언어 설정을 저장하지 못했습니다.": "无法保存语言设置。", "오피스 모드를 적용했습니다.": "已启用办公模式。", "오피스 모드를 해제했습니다.": "已关闭办公模式。", "전달할 다른 채팅방이 없습니다.": "没有其他可转发的聊天。", "전달에 실패했습니다.": "消息转发失败。", "신고 접수에 실패했습니다.": "举报提交失败。", "사진 파일을 읽지 못했습니다.": "无法读取照片文件。", "사진 전송 중 문제가 발생했습니다.": "发送照片时出现问题。", "파일 전송에 실패했습니다.": "文件发送失败。", "음성 전송에 실패했습니다.": "语音消息发送失败。", "새 그룹 이름을 입력하세요.": "输入新的群组名称。", "종료하지 못했습니다.": "无法结束群聊。", "그룹 채팅을 종료했습니다.": "群聊已结束。", "차단 해제": "解除屏蔽", "차단": "屏蔽", "상대방 프로필 보기": "查看个人资料", "설정을 변경하지 못했습니다.": "无法更改设置。", "브라우저 알림 권한이 허용되지 않았습니다.": "未授予浏览器通知权限。", "새 메시지가 도착했습니다.": "收到新消息。", "이메일이 변경되었습니다.": "邮箱已更改。", "이미지 파일만 선택할 수 있습니다.": "只能选择图像文件。", "그룹 사진 조절": "调整群组照片", "사진을 읽지 못했습니다. 다른 이미지 파일을 선택해주세요.": "无法读取照片。请选择其他图像文件。", "그룹 사진을 저장하지 못했습니다.": "无法保存群组照片。", "그룹 사진이 변경되었습니다.": "群组照片已更改。", "사진 저장 중 문제가 발생했습니다.": "保存照片时出现问题。", "동영상을 보내지 못했습니다.": "无法发送视频。", "동영상을 보냈습니다.": "视频已发送。", "동영상 전송 중 문제가 발생했습니다.": "发送视频时出现问题。"
    });
    Object.assign(dictionaries.ja, {
        "채팅 테마": "チャットテーマ", "↩️ 답장": "↩️ 返信", "채팅 테마 분류": "チャットテーマの分類", "프로필 사진 조절": "プロフィール写真を調整", "영문 소문자, 숫자 5자 이상": "英小文字・数字5文字以上", "가입할 때 등록한 이메일을 입력하면 아이디 안내 메일을 보내드립니다.": "登録時のメールアドレスを入力すると、ユーザー名の案内メールを送信します。", "가입 이메일로 인증번호를 받은 뒤 새 비밀번호를 설정하세요.": "登録メールで認証コードを受け取り、新しいパスワードを設定してください。", "새 비밀번호": "新しいパスワード",
        "관리자 페이지": "管理コンソール", "서비스 운영과 사용자 요청을 관리하는 공간입니다.": "サービス運営とユーザーリクエストを管理する画面です。", "보안 운영 세션 활성화": "安全な管理セッションが有効です", "메신저로 돌아가기": "メッセンジャーに戻る", "관리자 안내": "管理者向け案内", "관리자 권한이 확인되었습니다.": "管理者権限が確認されました。", "이 페이지는 서버에서 권한을 확인한 계정만 열 수 있습니다. 다음 단계에서 각 관리 메뉴를 연결합니다.": "サーバーで権限を確認したアカウントだけがこのページを開けます。", "관리 메뉴": "管理ツール", "공지사항 관리": "お知らせ管理", "새 공지 작성과 게시 상태를 한곳에서 관리합니다.": "お知らせの作成と公開状態を一か所で管理します。", "작성 기능 연결됨": "公開機能を接続済み", "문의 내역": "お問い合わせ履歴", "사용자가 보낸 문의와 첨부 파일을 확인하고 처리합니다.": "ユーザーからのお問い合わせと添付ファイルを確認・処理します。", "답변·상태 처리 연결됨": "返信・状態処理を接続済み", "신고 관리": "報告管理", "신고된 내용과 처리 결과를 안전하게 관리합니다.": "報告内容と対応結果を安全に管理します。", "접수 내역 확인 가능": "受付済みの報告を確認可能", "공지사항 작성": "お知らせを作成", "제목": "タイトル", "사용자에게 표시할 공지 제목": "ユーザーに表示するお知らせのタイトル", "내용": "内容", "공지 내용을 작성하세요.": "お知らせの内容を入力してください。", "바로 게시하기": "すぐに公開", "공지 등록": "お知らせを公開", "최근 공지": "最近のお知らせ", "불러오는 중...": "読み込み中…", "신고 내역": "報告履歴", "이용 제한 계정": "利用制限中のアカウント",
        "관리자 보안 확인": "管理者セキュリティ確認", "운영 콘솔에 들어가기 전, 재현님이 지정한 관리자 접근 키를 확인합니다. 인증은 30분 동안만 유지됩니다.": "管理コンソールに入る前に、設定した管理者アクセスキーを確認します。認証は30分間有効です。", "관리자 접근 키": "管理者アクセスキー", "보안 확인 후 계속": "確認して続行", "접근 키 설정이 필요합니다.": "アクセスキーの設定が必要です。", "Render 환경변수에": "Renderの環境変数に", "를 추가한 뒤 다시 시도해주세요.": "を追加して再試行してください。", "로그인으로 돌아가기": "ログインに戻る",
        "오피스 모드에서는 다크/라이트 모드를 변경할 수 없습니다.": "オフィスモードではダーク・ライトモードを変更できません。", "오피스 모드에서는 화면 모드 고정": "オフィスモードでは表示モードが固定されます", "언어 설정을 저장하지 못했습니다.": "言語設定を保存できませんでした。", "오피스 모드를 적용했습니다.": "オフィスモードを適用しました。", "오피스 모드를 해제했습니다.": "オフィスモードを解除しました。", "전달할 다른 채팅방이 없습니다.": "転送先の別のチャットがありません。", "전달에 실패했습니다.": "メッセージを転送できませんでした。", "신고 접수에 실패했습니다.": "報告を送信できませんでした。", "사진 파일을 읽지 못했습니다.": "写真ファイルを読み込めませんでした。", "사진 전송 중 문제가 발생했습니다.": "写真の送信中に問題が発生しました。", "파일 전송에 실패했습니다.": "ファイルを送信できませんでした。", "음성 전송에 실패했습니다.": "音声メッセージを送信できませんでした。", "새 그룹 이름을 입력하세요.": "新しいグループ名を入力してください。", "종료하지 못했습니다.": "グループチャットを終了できませんでした。", "그룹 채팅을 종료했습니다.": "グループチャットを終了しました。", "차단 해제": "ブロック解除", "차단": "ブロック", "상대방 프로필 보기": "相手のプロフィールを見る", "검색 중...": "検索中…", "친구": "友だち", "배경사진 없음": "背景写真なし", "설정을 변경하지 못했습니다.": "設定を変更できませんでした。", "브라우저 알림 권한이 허용되지 않았습니다.": "ブラウザ通知の権限が許可されませんでした。", "새 메시지가 도착했습니다.": "新しいメッセージが届きました。", "이메일이 변경되었습니다.": "メールアドレスが変更されました。", "이미지 파일만 선택할 수 있습니다.": "画像ファイルのみ選択できます。", "그룹 사진 조절": "グループ写真を調整", "사진을 읽지 못했습니다. 다른 이미지 파일을 선택해주세요.": "写真を読み込めませんでした。別の画像ファイルを選択してください。", "그룹 사진을 저장하지 못했습니다.": "グループ写真を保存できませんでした。", "그룹 사진이 변경되었습니다.": "グループ写真を変更しました。", "사진 저장 중 문제가 발생했습니다.": "写真の保存中に問題が発生しました。", "동영상을 보내지 못했습니다.": "動画を送信できませんでした。", "동영상을 보냈습니다.": "動画を送信しました。", "동영상 전송 중 문제가 발생했습니다.": "動画の送信中に問題が発生しました。"
    });
    Object.assign(dictionaries.es, {
        "채팅 테마": "Tema del chat", "↩️ 답장": "↩️ Responder", "채팅 테마 분류": "Categorías de temas", "프로필 사진 조절": "Ajustar foto de perfil", "영문 소문자, 숫자 5자 이상": "5+ letras minúsculas y números", "가입할 때 등록한 이메일을 입력하면 아이디 안내 메일을 보내드립니다.": "Introduce el correo usado al registrarte y enviaremos un recordatorio de usuario.", "가입 이메일로 인증번호를 받은 뒤 새 비밀번호를 설정하세요.": "Recibe un código en tu correo de registro y crea una nueva contraseña.", "새 비밀번호": "Nueva contraseña",
        "관리자 페이지": "Consola de administración", "서비스 운영과 사용자 요청을 관리하는 공간입니다.": "Gestiona las operaciones del servicio y las solicitudes de usuarios.", "보안 운영 세션 활성화": "Sesión segura de administración activa", "메신저로 돌아가기": "Volver al mensajero", "관리자 안내": "Aviso del administrador", "관리자 권한이 확인되었습니다.": "El acceso de administrador se ha verificado.", "이 페이지는 서버에서 권한을 확인한 계정만 열 수 있습니다. 다음 단계에서 각 관리 메뉴를 연결합니다.": "Solo las cuentas autorizadas por el servidor pueden abrir esta página.", "관리 메뉴": "Herramientas de gestión", "공지사항 관리": "Gestión de avisos", "새 공지 작성과 게시 상태를 한곳에서 관리합니다.": "Crea avisos y gestiona su publicación en un solo lugar.", "작성 기능 연결됨": "Herramientas de publicación conectadas", "문의 내역": "Historial de consultas", "사용자가 보낸 문의와 첨부 파일을 확인하고 처리합니다.": "Revisa y gestiona las consultas y archivos adjuntos de usuarios.", "답변·상태 처리 연결됨": "Herramientas de respuesta y estado conectadas", "신고 관리": "Gestión de denuncias", "신고된 내용과 처리 결과를 안전하게 관리합니다.": "Gestiona de forma segura los reportes y resultados de moderación.", "접수 내역 확인 가능": "Reportes enviados disponibles", "공지사항 작성": "Crear aviso", "제목": "Título", "사용자에게 표시할 공지 제목": "Título del aviso visible para usuarios", "내용": "Contenido", "공지 내용을 작성하세요.": "Escribe el contenido del aviso.", "바로 게시하기": "Publicar ahora", "공지 등록": "Publicar aviso", "최근 공지": "Avisos recientes", "불러오는 중...": "Cargando…", "신고 내역": "Denuncias", "이용 제한 계정": "Cuentas restringidas",
        "관리자 보안 확인": "Verificación de seguridad de administrador", "운영 콘솔에 들어가기 전, 재현님이 지정한 관리자 접근 키를 확인합니다. 인증은 30분 동안만 유지됩니다.": "Antes de abrir la consola, verifica la clave de acceso del administrador. La verificación dura 30 minutos.", "관리자 접근 키": "Clave de acceso de administrador", "보안 확인 후 계속": "Verificar y continuar", "접근 키 설정이 필요합니다.": "Debes configurar una clave de acceso.", "Render 환경변수에": "En las variables de entorno de Render, añade", "를 추가한 뒤 다시 시도해주세요.": "y vuelve a intentarlo.", "로그인으로 돌아가기": "Volver al inicio de sesión",
        "오피스 모드에서는 다크/라이트 모드를 변경할 수 없습니다.": "No puedes cambiar entre modo oscuro y claro en modo oficina.", "오피스 모드에서는 화면 모드 고정": "El modo de pantalla está fijo en modo oficina", "언어 설정을 저장하지 못했습니다.": "No se pudo guardar la configuración de idioma.", "오피스 모드를 적용했습니다.": "Modo oficina activado.", "오피스 모드를 해제했습니다.": "Modo oficina desactivado.", "전달할 다른 채팅방이 없습니다.": "No hay otros chats a los que reenviar.", "전달에 실패했습니다.": "No se pudo reenviar el mensaje.", "신고 접수에 실패했습니다.": "No se pudo enviar la denuncia.", "사진 파일을 읽지 못했습니다.": "No se pudo leer el archivo de foto.", "사진 전송 중 문제가 발생했습니다.": "Ocurrió un problema al enviar la foto.", "파일 전송에 실패했습니다.": "No se pudo enviar el archivo.", "음성 전송에 실패했습니다.": "No se pudo enviar el mensaje de voz.", "새 그룹 이름을 입력하세요.": "Introduce un nuevo nombre de grupo.", "종료하지 못했습니다.": "No se pudo finalizar el chat grupal.", "그룹 채팅을 종료했습니다.": "Chat grupal finalizado.", "차단 해제": "Desbloquear", "차단": "Bloquear", "설정을 변경하지 못했습니다.": "No se pudo cambiar la configuración.", "브라우저 알림 권한이 허용되지 않았습니다.": "No se concedió permiso de notificaciones del navegador.", "새 메시지가 도착했습니다.": "Ha llegado un mensaje nuevo.", "이메일이 변경되었습니다.": "Correo cambiado.", "이미지 파일만 선택할 수 있습니다.": "Solo se pueden seleccionar archivos de imagen.", "그룹 사진 조절": "Ajustar foto del grupo", "사진을 읽지 못했습니다. 다른 이미지 파일을 선택해주세요.": "No se pudo leer la foto. Elige otro archivo de imagen.", "그룹 사진을 저장하지 못했습니다.": "No se pudo guardar la foto del grupo.", "그룹 사진이 변경되었습니다.": "Foto del grupo cambiada.", "사진 저장 중 문제가 발생했습니다.": "Ocurrió un problema al guardar la foto.", "동영상을 보내지 못했습니다.": "No se pudo enviar el vídeo.", "동영상을 보냈습니다.": "Vídeo enviado.", "동영상 전송 중 문제가 발생했습니다.": "Ocurrió un problema al enviar el vídeo."
    });
    // 약관 원문도 별도 페이지에서 열리므로, 본문까지 같은 언어 규칙을 적용한다.
    Object.assign(dictionaries.en, {
        "시행일: 2026년 8월 14일": "Effective date: August 14, 2026", "1. 수집하는 정보": "1. Information we collect", "Cloud Chatting은 회원가입과 서비스 제공을 위해 아이디, 이메일 주소, 비밀번호 해시, 표시 이름, 프로필 사진 및 서비스 이용 중 생성한 메시지·첨부 파일을 처리합니다.": "Cloud Chatting processes usernames, email addresses, password hashes, display names, profile photos, and messages and attachments created while using the service for registration and service delivery.", "2. 이용 목적": "2. Purpose of use", "회원 식별, 로그인 인증, 메시지 전달, 고객 문의 처리, 서비스 안정성 및 부정 이용 방지에 사용합니다.": "We use this information for member identification, login verification, message delivery, customer inquiries, service stability, and prevention of misuse.", "3. 보관 및 삭제": "3. Retention and deletion", "회원 탈퇴 시 관련 계정 정보는 삭제합니다. 법령상 보관 의무가 있는 정보는 해당 기간 동안 보관할 수 있습니다.": "Related account information is deleted upon account withdrawal. Information required by law may be retained for the required period.", "4. 문의": "4. Contact", "개인정보 관련 요청은 서비스 내 공지사항·도움말의 문의 기능으로 접수할 수 있습니다.": "Privacy-related requests can be submitted through the inquiry feature in Notices & Help.", "1. 서비스 이용": "1. Use of service", "Cloud Chatting은 사용자 간 대화와 파일 공유 기능을 제공합니다. 사용자는 관련 법령과 본 약관을 준수해야 합니다.": "Cloud Chatting provides conversations and file sharing between users. Users must comply with applicable laws and these terms.", "2. 금지 행위": "2. Prohibited conduct", "스팸, 사칭, 타인 괴롭힘, 불법 정보 유통, 서비스 운영을 방해하는 행위는 금지됩니다. 위반 콘텐츠는 신고 및 운영자 검토를 통해 제한될 수 있습니다.": "Spam, impersonation, harassment, distribution of illegal information, and interference with the service are prohibited. Violating content may be restricted through reports and administrator review.", "3. 계정 관리": "3. Account management", "계정 비밀번호와 인증 수단의 관리 책임은 사용자에게 있습니다. 의심스러운 접근이 확인되면 비밀번호를 변경해주세요.": "Users are responsible for managing account passwords and verification methods. Change your password if suspicious access is detected.", "4. 약관 변경": "4. Changes to these terms", "중요한 변경 사항은 서비스 공지사항을 통해 안내합니다.": "Important changes will be announced through service notices."
    });
    Object.assign(dictionaries.zh, {
        "시행일: 2026년 8월 14일": "生效日期：2026年8月14日", "1. 수집하는 정보": "1. 收集的信息", "Cloud Chatting은 회원가입과 서비스 제공을 위해 아이디, 이메일 주소, 비밀번호 해시, 표시 이름, 프로필 사진 및 서비스 이용 중 생성한 메시지·첨부 파일을 처리합니다.": "为注册和提供服务，Cloud Chatting 会处理用户名、邮箱、密码哈希、显示名称、头像以及使用服务时生成的消息和附件。", "2. 이용 목적": "2. 使用目的", "회원 식별, 로그인 인증, 메시지 전달, 고객 문의 처리, 서비스 안정성 및 부정 이용 방지에 사용합니다.": "用于会员识别、登录验证、消息传递、客户咨询处理、服务稳定性及防止不当使用。", "3. 보관 및 삭제": "3. 保存和删除", "회원 탈퇴 시 관련 계정 정보는 삭제합니다. 법령상 보관 의무가 있는 정보는 해당 기간 동안 보관할 수 있습니다.": "注销账户时会删除相关账户信息。法律要求保存的信息可能会在规定期间保留。", "4. 문의": "4. 联系方式", "개인정보 관련 요청은 서비스 내 공지사항·도움말의 문의 기능으로 접수할 수 있습니다.": "与隐私相关的请求可通过服务内公告和帮助中的咨询功能提交。", "1. 서비스 이용": "1. 服务使用", "Cloud Chatting은 사용자 간 대화와 파일 공유 기능을 제공합니다. 사용자는 관련 법령과 본 약관을 준수해야 합니다.": "Cloud Chatting 提供用户之间的聊天和文件共享功能。用户必须遵守相关法律和本条款。", "2. 금지 행위": "2. 禁止行为", "스팸, 사칭, 타인 괴롭힘, 불법 정보 유통, 서비스 운영을 방해하는 행위는 금지됩니다. 위반 콘텐츠는 신고 및 운영자 검토를 통해 제한될 수 있습니다.": "禁止垃圾信息、冒充、骚扰他人、传播非法信息及妨碍服务运营。违规内容可能通过举报和管理员审核受到限制。", "3. 계정 관리": "3. 账户管理", "계정 비밀번호와 인증 수단의 관리 책임은 사용자에게 있습니다. 의심스러운 접근이 확인되면 비밀번호를 변경해주세요.": "用户负责管理账户密码和验证方式。如发现可疑访问，请更改密码。", "4. 약관 변경": "4. 条款变更", "중요한 변경 사항은 서비스 공지사항을 통해 안내합니다.": "重要变更将通过服务公告通知。"
    });
    Object.assign(dictionaries.ja, {
        "시행일: 2026년 8월 14일": "施行日：2026年8月14日", "1. 수집하는 정보": "1. 取得する情報", "Cloud Chatting은 회원가입과 서비스 제공을 위해 아이디, 이메일 주소, 비밀번호 해시, 표시 이름, 프로필 사진 및 서비스 이용 중 생성한 메시지·첨부 파일을 처리합니다.": "Cloud Chattingは登録およびサービス提供のため、ユーザー名、メールアドレス、パスワードハッシュ、表示名、プロフィール写真、サービス利用中に作成されたメッセージと添付ファイルを処理します。", "2. 이용 목적": "2. 利用目的", "회원 식별, 로그인 인증, 메시지 전달, 고객 문의 처리, 서비스 안정성 및 부정 이용 방지에 사용합니다.": "会員の識別、ログイン認証、メッセージ配信、お問い合わせ対応、サービスの安定性、不正利用防止に使用します。", "3. 보관 및 삭제": "3. 保管と削除", "회원 탈퇴 시 관련 계정 정보는 삭제합니다. 법령상 보관 의무가 있는 정보는 해당 기간 동안 보관할 수 있습니다.": "退会時に関連するアカウント情報を削除します。法令により保管義務がある情報は、その期間保管する場合があります。", "4. 문의": "4. お問い合わせ", "개인정보 관련 요청은 서비스 내 공지사항·도움말의 문의 기능으로 접수할 수 있습니다.": "プライバシーに関するご要望は、サービス内のお知らせ・ヘルプのお問い合わせ機能から受け付けます。", "1. 서비스 이용": "1. サービスの利用", "Cloud Chatting은 사용자 간 대화와 파일 공유 기능을 제공합니다. 사용자는 관련 법령과 본 약관을 준수해야 합니다.": "Cloud Chattingはユーザー間の会話とファイル共有機能を提供します。ユーザーは関連法令と本規約を遵守する必要があります。", "2. 금지 행위": "2. 禁止行為", "스팸, 사칭, 타인 괴롭힘, 불법 정보 유통, 서비스 운영을 방해하는 행위는 금지됩니다. 위반 콘텐츠는 신고 및 운영자 검토를 통해 제한될 수 있습니다.": "スパム、なりすまし、他者への嫌がらせ、違法情報の流通、サービス運営を妨げる行為は禁止です。違反コンテンツは報告と運営者の確認により制限される場合があります。", "3. 계정 관리": "3. アカウント管理", "계정 비밀번호와 인증 수단의 관리 책임은 사용자에게 있습니다. 의심스러운 접근이 확인되면 비밀번호를 변경해주세요.": "アカウントのパスワードと認証手段の管理責任はユーザーにあります。不審なアクセスが確認された場合はパスワードを変更してください。", "4. 약관 변경": "4. 規約の変更", "중요한 변경 사항은 서비스 공지사항을 통해 안내합니다.": "重要な変更はサービスのお知らせで案内します。"
    });
    Object.assign(dictionaries.es, {
        "시행일: 2026년 8월 14일": "Fecha de entrada en vigor: 14 de agosto de 2026", "1. 수집하는 정보": "1. Información que recopilamos", "Cloud Chatting은 회원가입과 서비스 제공을 위해 아이디, 이메일 주소, 비밀번호 해시, 표시 이름, 프로필 사진 및 서비스 이용 중 생성한 메시지·첨부 파일을 처리합니다.": "Cloud Chatting procesa nombres de usuario, direcciones de correo, hashes de contraseñas, nombres visibles, fotos de perfil y mensajes y archivos adjuntos creados durante el uso del servicio para el registro y la prestación del servicio.", "2. 이용 목적": "2. Finalidad de uso", "회원 식별, 로그인 인증, 메시지 전달, 고객 문의 처리, 서비스 안정성 및 부정 이용 방지에 사용합니다.": "Usamos esta información para identificar miembros, verificar inicios de sesión, entregar mensajes, atender consultas, mantener la estabilidad y prevenir usos indebidos.", "3. 보관 및 삭제": "3. Conservación y eliminación", "회원 탈퇴 시 관련 계정 정보는 삭제합니다. 법령상 보관 의무가 있는 정보는 해당 기간 동안 보관할 수 있습니다.": "La información relacionada se elimina al cerrar la cuenta. La información requerida por ley puede conservarse durante el periodo exigido.", "4. 문의": "4. Contacto", "개인정보 관련 요청은 서비스 내 공지사항·도움말의 문의 기능으로 접수할 수 있습니다.": "Las solicitudes de privacidad se pueden enviar mediante la función de consultas de Avisos y ayuda.", "1. 서비스 이용": "1. Uso del servicio", "Cloud Chatting은 사용자 간 대화와 파일 공유 기능을 제공합니다. 사용자는 관련 법령과 본 약관을 준수해야 합니다.": "Cloud Chatting ofrece conversaciones y uso compartido de archivos entre usuarios. Los usuarios deben cumplir las leyes aplicables y estos términos.", "2. 금지 행위": "2. Conductas prohibidas", "스팸, 사칭, 타인 괴롭힘, 불법 정보 유통, 서비스 운영을 방해하는 행위는 금지됩니다. 위반 콘텐츠는 신고 및 운영자 검토를 통해 제한될 수 있습니다.": "Se prohíben el spam, la suplantación, el acoso, la distribución de información ilegal y la interferencia con el servicio. El contenido infractor puede restringirse mediante denuncias y revisión administrativa.", "3. 계정 관리": "3. Gestión de cuenta", "계정 비밀번호와 인증 수단의 관리 책임은 사용자에게 있습니다. 의심스러운 접근이 확인되면 비밀번호를 변경해주세요.": "Los usuarios son responsables de gestionar sus contraseñas y métodos de verificación. Cambia la contraseña si detectas un acceso sospechoso.", "4. 약관 변경": "4. Cambios en los términos", "중요한 변경 사항은 서비스 공지사항을 통해 안내합니다.": "Los cambios importantes se anunciarán en los avisos del servicio."
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
    // 전수 점검에서 확인된 로그인·관리자·고정 안내 문구다.
    Object.assign(dictionaries.en, {
        "채팅 테마": "Chat theme", "↩️ 답장": "↩️ Reply", "채팅 테마 분류": "Chat theme categories", "프로필 사진 조절": "Adjust profile photo", "영문 소문자, 숫자 5자 이상": "5+ lowercase letters and numbers", "가입할 때 등록한 이메일을 입력하면 아이디 안내 메일을 보내드립니다.": "Enter the email used for registration and we will send a username reminder.", "가입 이메일로 인증번호를 받은 뒤 새 비밀번호를 설정하세요.": "Receive a verification code at your registration email, then set a new password.", "새 비밀번호": "New password",
        "관리자 페이지": "Admin console", "서비스 운영과 사용자 요청을 관리하는 공간입니다.": "Manage service operations and user requests.", "보안 운영 세션 활성화": "Secure admin session active", "메신저로 돌아가기": "Return to messenger", "관리자 안내": "Administrator notice", "관리자 권한이 확인되었습니다.": "Administrator access has been verified.", "이 페이지는 서버에서 권한을 확인한 계정만 열 수 있습니다. 다음 단계에서 각 관리 메뉴를 연결합니다.": "Only accounts authorized by the server can open this page. Connect each management tool in the next step.", "관리 메뉴": "Management tools", "공지사항 관리": "Notice management", "새 공지 작성과 게시 상태를 한곳에서 관리합니다.": "Create notices and manage their publication status in one place.", "작성 기능 연결됨": "Publishing tools connected", "문의 내역": "Inquiry history", "사용자가 보낸 문의와 첨부 파일을 확인하고 처리합니다.": "Review and handle user inquiries and attachments.", "답변·상태 처리 연결됨": "Reply and status tools connected", "신고 관리": "Report management", "신고된 내용과 처리 결과를 안전하게 관리합니다.": "Manage reports and moderation results safely.", "접수 내역 확인 가능": "Submitted reports available", "공지사항 작성": "Create notice", "제목": "Title", "사용자에게 표시할 공지 제목": "Notice title shown to users", "내용": "Content", "공지 내용을 작성하세요.": "Write the notice content.", "바로 게시하기": "Publish immediately", "공지 등록": "Publish notice", "최근 공지": "Recent notices", "불러오는 중...": "Loading...", "신고 내역": "Reports", "이용 제한 계정": "Restricted accounts",
        "관리자 보안 확인": "Admin security check", "운영 콘솔에 들어가기 전, 재현님이 지정한 관리자 접근 키를 확인합니다. 인증은 30분 동안만 유지됩니다.": "Before opening the admin console, confirm the administrator access key set by 재현님. Verification remains valid for 30 minutes.", "관리자 접근 키": "Administrator access key", "보안 확인 후 계속": "Verify and continue", "접근 키 설정이 필요합니다.": "An access key must be configured.", "Render 환경변수에": "In Render environment variables, add", "를 추가한 뒤 다시 시도해주세요.": "and try again.", "로그인으로 돌아가기": "Return to login",
        "오피스 모드에서는 다크/라이트 모드를 변경할 수 없습니다.": "Dark and light modes cannot be changed in office mode.", "오피스 모드에서는 화면 모드 고정": "Display mode is fixed in office mode", "언어 설정을 저장하지 못했습니다.": "Could not save language setting.", "오피스 모드를 적용했습니다.": "Office mode enabled.", "오피스 모드를 해제했습니다.": "Office mode disabled.", "전달할 다른 채팅방이 없습니다.": "There are no other chats to forward to.", "전달에 실패했습니다.": "Could not forward the message.", "신고 접수에 실패했습니다.": "Could not submit the report.", "사진 파일을 읽지 못했습니다.": "Could not read the photo file.", "사진 전송 중 문제가 발생했습니다.": "A problem occurred while sending the photo.", "파일 전송에 실패했습니다.": "Could not send the file.", "음성 전송에 실패했습니다.": "Could not send the voice message.", "새 그룹 이름을 입력하세요.": "Enter a new group name.", "종료하지 못했습니다.": "Could not end the group chat.", "그룹 채팅을 종료했습니다.": "Group chat ended.", "차단 해제": "Unblock", "차단": "Block", "상대방 프로필 보기": "View profile", "설정을 변경하지 못했습니다.": "Could not change settings.", "브라우저 알림 권한이 허용되지 않았습니다.": "Browser notification permission was not granted.", "새 메시지가 도착했습니다.": "A new message has arrived.", "이메일이 변경되었습니다.": "Email address changed.", "이미지 파일만 선택할 수 있습니다.": "Only image files can be selected.", "그룹 사진 조절": "Adjust group photo", "사진을 읽지 못했습니다. 다른 이미지 파일을 선택해주세요.": "Could not read the photo. Choose another image file.", "그룹 사진을 저장하지 못했습니다.": "Could not save the group photo.", "그룹 사진이 변경되었습니다.": "Group photo changed.", "사진 저장 중 문제가 발생했습니다.": "A problem occurred while saving the photo.", "동영상을 보내지 못했습니다.": "Could not send the video.", "동영상을 보냈습니다.": "Video sent.", "동영상 전송 중 문제가 발생했습니다.": "A problem occurred while sending the video."
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

    // 영어 대체 문구로만 남지 않도록, 설명형 UI도 중국어·일본어·스페인어별 표현을 둔다.
    Object.assign(dictionaries.zh, {
        "현재 대화": "当前对话", "친구를 추가하거나 채팅방을 선택해보세요.": "添加好友或选择一个聊天。", "대화를 선택해 시작하세요": "选择对话以开始", "친구를 추가하고 대화를 시작해보세요!": "添加好友并开始聊天吧！", "아직 대화가 없어요. 메시지를 보내보세요!": "还没有消息，发送一条消息吧！",
        "공지사항": "公告", "현재 등록된 공지사항이 없습니다.": "暂无公告。", "도움말": "帮助", "불편한 점이나 개선 의견을 남겨주시면 이메일로 직접 전달됩니다.": "提交问题或改进建议后，将通过电子邮件直接发送给我们。", "계정 복구": "账户恢复", "로그인 중에도 아이디 안내와 비밀번호 재설정을 이용할 수 있습니다.": "您可以在此找回用户名或重置密码。",
        "문의 보내기": "联系支持", "문의 내용은 10자 이상 작성해주세요. 사진 또는 동영상은 선택 사항입니다.": "请至少输入 10 个字符。照片或视频为可选项。", "어떤 점이 불편했는지 자세히 알려주세요.": "请详细说明遇到的问题。", "사진 · 동영상 첨부": "附加照片或视频", "선택": "可选", "첨부 파일 없음": "未附加文件", "문의 전송하기": "发送咨询",
        "내 문의 내역": "我的咨询", "답변을 확인하고, 답변 전 문의는 수정하거나 삭제할 수 있습니다.": "您可以查看答复，并在答复前编辑或删除咨询。", "보낸 문의가 없습니다.": "尚未发送咨询。", "운영 안내": "服务通知", "운영팀에서 전달한 경고 및 이용 관련 안내를 확인할 수 있습니다.": "您可以查看运营团队发送的警告和使用通知。", "받은 운영 안내가 없습니다.": "没有收到服务通知。",
        "사용자 리뷰": "用户评价", "Cloud Chatting을 사용하며 느낀 점을 남겨주세요.": "分享您使用 Cloud Chatting 的感受。", "리뷰 작성": "撰写评价", "별점 선택": "选择评分", "후기 5자 이상": "评价（至少 5 个字符）", "리뷰 등록": "提交评价", "모든 리뷰": "全部评价", "관리자 답변을 확인할 수 있어요.": "可以查看管理员回复。", "첫 번째 리뷰를 남겨주세요.": "成为第一个留下评价的人吧。",
        "새 메시지 알림": "新消息通知", "친구 요청 알림": "好友请求通知", "그룹 초대 알림": "群组邀请通知", "브라우저 알림": "浏览器通知", "업데이트 사항": "更新内容", "최근 10개": "最近 10 条", "이전 업데이트 사항": "历史更新", "업데이트 내역을 불러오는 중입니다.": "正在加载更新记录…", "업데이트": "更新",
        "현재 이메일:": "当前邮箱：", "새 이메일 주소": "新邮箱地址", "인증코드 받기": "发送验证码", "인증코드 6자리": "6 位验证码", "현재 비밀번호": "当前密码", "이메일 변경": "更改邮箱", "아이디 변경": "更改用户名", "새 아이디 (소문자+숫자 5자 이상)": "新用户名（至少 5 位小写字母和数字）", "아이디 저장": "保存用户名", "새 비밀번호 (소문자+숫자+특수문자 7자 이상)": "新密码（至少 7 位小写字母、数字和符号）", "비밀번호 저장": "保存密码", "계정 삭제": "删除账户", "계정 삭제하기": "删除账户",
        "채팅방 목록으로 돌아가기": "返回聊天列表", "채팅방 더보기": "更多聊天选项", "메시지 검색...": "搜索消息…", "메시지 전달": "转发消息", "전달할 채팅방을 선택해주세요.": "请选择要转发到的聊天。", "전달하기": "转发", "메시지 신고": "举报消息", "신고 사유 선택": "选择举报原因", "추가 설명 (선택)": "补充说明（可选）", "신고 접수하기": "提交举报",
        "계정으로 로그인해서 대화를 이어가세요.": "登录您的账户以继续对话。", "이메일 인증 후 비밀번호를 정해주세요.": "验证邮箱后设置密码。", "가입하고 시작하기": "注册并开始", "영문 소문자, 숫자, 특수문자 7자 이상": "至少 7 位小写字母、数字和符号", "인증번호를 입력한 뒤 이메일 인증을 완료해주세요.": "输入验证码以完成邮箱验证。", "재전송": "重新发送", "인증번호가 변경되어 다시 인증이 필요합니다.": "验证码已更改，请重新验证。", "이메일이 변경되어 인증번호를 다시 받아야 합니다.": "邮箱已更改，请重新获取验证码。"
    });
    Object.assign(dictionaries.ja, {
        "현재 대화": "現在の会話", "친구를 추가하거나 채팅방을 선택해보세요.": "友だちを追加するか、チャットを選択してください。", "대화를 선택해 시작하세요": "会話を選んで開始", "친구를 추가하고 대화를 시작해보세요!": "友だちを追加して会話を始めましょう！", "아직 대화가 없어요. 메시지를 보내보세요!": "まだメッセージはありません。送ってみましょう！",
        "공지사항": "お知らせ", "현재 등록된 공지사항이 없습니다.": "お知らせはありません。", "도움말": "ヘルプ", "불편한 점이나 개선 의견을 남겨주시면 이메일로 직접 전달됩니다.": "問題や改善のご意見を送ると、メールで直接届きます。", "계정 복구": "アカウント復旧", "로그인 중에도 아이디 안내와 비밀번호 재설정을 이용할 수 있습니다.": "ここでユーザー名の確認やパスワードの再設定ができます。",
        "문의 보내기": "お問い合わせ", "문의 내용은 10자 이상 작성해주세요. 사진 또는 동영상은 선택 사항입니다.": "10文字以上で入力してください。写真・動画は任意です。", "어떤 점이 불편했는지 자세히 알려주세요.": "困った点を詳しく教えてください。", "사진 · 동영상 첨부": "写真・動画を添付", "선택": "任意", "첨부 파일 없음": "添付ファイルなし", "문의 전송하기": "お問い合わせを送信",
        "내 문의 내역": "お問い合わせ履歴", "답변을 확인하고, 답변 전 문의는 수정하거나 삭제할 수 있습니다.": "返信を確認できます。返信前のお問い合わせは編集・削除できます。", "보낸 문의가 없습니다.": "送信したお問い合わせはありません。", "운영 안내": "運営からのお知らせ", "운영팀에서 전달한 경고 및 이용 관련 안내를 확인할 수 있습니다.": "運営チームからの警告や利用に関する案内を確認できます。", "받은 운영 안내가 없습니다.": "運営からのお知らせはありません。",
        "사용자 리뷰": "ユーザーレビュー", "Cloud Chatting을 사용하며 느낀 점을 남겨주세요.": "Cloud Chattingを使った感想をお寄せください。", "리뷰 작성": "レビューを書く", "별점 선택": "評価を選択", "후기 5자 이상": "レビュー（5文字以上）", "리뷰 등록": "レビューを投稿", "모든 리뷰": "すべてのレビュー", "관리자 답변을 확인할 수 있어요.": "管理者の返信を確認できます。", "첫 번째 리뷰를 남겨주세요.": "最初のレビューを投稿しましょう。",
        "새 메시지 알림": "新着メッセージ通知", "친구 요청 알림": "友だちリクエスト通知", "그룹 초대 알림": "グループ招待通知", "브라우저 알림": "ブラウザ通知", "업데이트 사항": "アップデート", "최근 10개": "最新10件", "이전 업데이트 사항": "過去のアップデート", "업데이트 내역을 불러오는 중입니다.": "アップデート履歴を読み込み中…", "업데이트": "アップデート",
        "현재 이메일:": "現在のメール：", "새 이메일 주소": "新しいメールアドレス", "인증코드 받기": "認証コードを送信", "인증코드 6자리": "6桁の認証コード", "현재 비밀번호": "現在のパスワード", "이메일 변경": "メールアドレスを変更", "아이디 변경": "ユーザー名を変更", "새 아이디 (소문자+숫자 5자 이상)": "新しいユーザー名（英小文字・数字5文字以上）", "아이디 저장": "ユーザー名を保存", "새 비밀번호 (소문자+숫자+특수문자 7자 이상)": "新しいパスワード（英小文字・数字・記号7文字以上）", "비밀번호 저장": "パスワードを保存", "계정 삭제": "アカウント削除", "계정 삭제하기": "アカウントを削除",
        "채팅방 목록으로 돌아가기": "チャット一覧に戻る", "채팅방 더보기": "チャットのその他の操作", "메시지 검색...": "メッセージを検索…", "메시지 전달": "メッセージを転送", "전달할 채팅방을 선택해주세요.": "転送先のチャットを選択してください。", "전달하기": "転送", "메시지 신고": "メッセージを報告", "신고 사유 선택": "報告理由を選択", "추가 설명 (선택)": "追加説明（任意）", "신고 접수하기": "報告を送信",
        "계정으로 로그인해서 대화를 이어가세요.": "アカウントにログインして会話を続けましょう。", "이메일 인증 후 비밀번호를 정해주세요.": "メール認証後にパスワードを設定してください。", "가입하고 시작하기": "登録して始める", "영문 소문자, 숫자, 특수문자 7자 이상": "英小文字・数字・記号を含む7文字以上", "인증번호를 입력한 뒤 이메일 인증을 완료해주세요.": "認証コードを入力してメール認証を完了してください。", "재전송": "再送信", "인증번호가 변경되어 다시 인증이 필요합니다.": "認証コードが変更されました。もう一度認証してください。", "이메일이 변경되어 인증번호를 다시 받아야 합니다.": "メールアドレスが変更されました。認証コードを再取得してください。"
    });
    Object.assign(dictionaries.es, {
        "현재 대화": "Conversación actual", "친구를 추가하거나 채팅방을 선택해보세요.": "Añade un amigo o selecciona un chat.", "대화를 선택해 시작하세요": "Selecciona una conversación para empezar", "친구를 추가하고 대화를 시작해보세요!": "Añade un amigo y empieza a conversar.", "아직 대화가 없어요. 메시지를 보내보세요!": "Aún no hay mensajes. ¡Envía uno!",
        "공지사항": "Avisos", "현재 등록된 공지사항이 없습니다.": "No hay avisos.", "도움말": "Ayuda", "불편한 점이나 개선 의견을 남겨주시면 이메일로 직접 전달됩니다.": "Envía un problema o una sugerencia y se entregará por correo electrónico.", "계정 복구": "Recuperación de cuenta", "로그인 중에도 아이디 안내와 비밀번호 재설정을 이용할 수 있습니다.": "Aquí puedes encontrar tu usuario o restablecer la contraseña.",
        "문의 보내기": "Contactar con soporte", "문의 내용은 10자 이상 작성해주세요. 사진 또는 동영상은 선택 사항입니다.": "Escribe al menos 10 caracteres. Las fotos y vídeos son opcionales.", "어떤 점이 불편했는지 자세히 알려주세요.": "Cuéntanos en detalle qué fue inconveniente.", "사진 · 동영상 첨부": "Adjuntar foto o vídeo", "선택": "Opcional", "첨부 파일 없음": "Sin archivo adjunto", "문의 전송하기": "Enviar consulta",
        "내 문의 내역": "Mis consultas", "답변을 확인하고, 답변 전 문의는 수정하거나 삭제할 수 있습니다.": "Consulta las respuestas y edita o elimina tus consultas antes de recibir una respuesta.", "보낸 문의가 없습니다.": "No has enviado consultas.", "운영 안내": "Avisos del servicio", "운영팀에서 전달한 경고 및 이용 관련 안내를 확인할 수 있습니다.": "Consulta advertencias y avisos del equipo de moderación.", "받은 운영 안내가 없습니다.": "No hay avisos del servicio.",
        "사용자 리뷰": "Reseñas de usuarios", "Cloud Chatting을 사용하며 느낀 점을 남겨주세요.": "Comparte tu experiencia usando Cloud Chatting.", "리뷰 작성": "Escribir una reseña", "별점 선택": "Seleccionar valoración", "후기 5자 이상": "Reseña (5+ caracteres)", "리뷰 등록": "Enviar reseña", "모든 리뷰": "Todas las reseñas", "관리자 답변을 확인할 수 있어요.": "Puedes ver las respuestas del administrador.", "첫 번째 리뷰를 남겨주세요.": "Sé la primera persona en dejar una reseña.",
        "새 메시지 알림": "Notificaciones de mensajes", "친구 요청 알림": "Notificaciones de solicitudes", "그룹 초대 알림": "Notificaciones de invitaciones", "브라우저 알림": "Notificaciones del navegador", "업데이트 사항": "Actualizaciones", "최근 10개": "Últimas 10", "이전 업데이트 사항": "Actualizaciones anteriores", "업데이트 내역을 불러오는 중입니다.": "Cargando historial de actualizaciones…", "업데이트": "Actualización",
        "현재 이메일:": "Correo actual:", "새 이메일 주소": "Nueva dirección de correo", "인증코드 받기": "Enviar código de verificación", "인증코드 6자리": "Código de 6 dígitos", "현재 비밀번호": "Contraseña actual", "이메일 변경": "Cambiar correo", "아이디 변경": "Cambiar usuario", "새 아이디 (소문자+숫자 5자 이상)": "Nuevo usuario (5+ letras minúsculas y números)", "아이디 저장": "Guardar usuario", "새 비밀번호 (소문자+숫자+특수문자 7자 이상)": "Nueva contraseña (7+ minúsculas, números y símbolos)", "비밀번호 저장": "Guardar contraseña", "계정 삭제": "Eliminar cuenta", "계정 삭제하기": "Eliminar cuenta",
        "채팅방 목록으로 돌아가기": "Volver a la lista de chats", "채팅방 더보기": "Más opciones del chat", "메시지 검색...": "Buscar mensajes…", "메시지 전달": "Reenviar mensaje", "전달할 채팅방을 선택해주세요.": "Selecciona un chat al que reenviar.", "전달하기": "Reenviar", "메시지 신고": "Denunciar mensaje", "신고 사유 선택": "Selecciona un motivo", "추가 설명 (선택)": "Detalles adicionales (opcional)", "신고 접수하기": "Enviar denuncia",
        "계정으로 로그인해서 대화를 이어가세요.": "Inicia sesión en tu cuenta para continuar tus conversaciones.", "이메일 인증 후 비밀번호를 정해주세요.": "Verifica tu correo y luego crea una contraseña.", "가입하고 시작하기": "Registrarse y empezar", "영문 소문자, 숫자, 특수문자 7자 이상": "7+ minúsculas, números y símbolos", "인증번호를 입력한 뒤 이메일 인증을 완료해주세요.": "Introduce el código y completa la verificación del correo.", "재전송": "Reenviar", "인증번호가 변경되어 다시 인증이 필요합니다.": "El código cambió. Verifica de nuevo.", "이메일이 변경되어 인증번호를 다시 받아야 합니다.": "El correo cambió. Solicita un nuevo código."
    });
    Object.assign(dictionaries.en, {
        "클라우드 채팅": "Cloud Chatting", "로그인 - cloudchatting 계정": "Log in - Cloud Chatting account", "관리자 페이지 - Cloud Chatting": "Admin console - Cloud Chatting", "관리자 보안 확인 - Cloud Chatting": "Admin security check - Cloud Chatting", "개인정보처리방침": "Privacy policy", "이용약관": "Terms of service", "개인정보처리방침 - Cloud Chatting": "Privacy policy - Cloud Chatting", "이용약관 - Cloud Chatting": "Terms of service - Cloud Chatting"
    });
    Object.assign(dictionaries.zh, {
        "클라우드 채팅": "云端聊天", "로그인 - cloudchatting 계정": "登录 - 云端聊天账户", "관리자 페이지 - Cloud Chatting": "管理控制台 - 云端聊天", "관리자 보안 확인 - Cloud Chatting": "管理员安全验证 - 云端聊天", "개인정보처리방침": "隐私政策", "이용약관": "服务条款", "개인정보처리방침 - Cloud Chatting": "隐私政策 - 云端聊天", "이용약관 - Cloud Chatting": "服务条款 - 云端聊天"
    });
    Object.assign(dictionaries.ja, {
        "클라우드 채팅": "クラウドチャット", "로그인 - cloudchatting 계정": "ログイン - Cloud Chattingアカウント", "관리자 페이지 - Cloud Chatting": "管理コンソール - Cloud Chatting", "관리자 보안 확인 - Cloud Chatting": "管理者セキュリティ確認 - Cloud Chatting", "개인정보처리방침": "プライバシーポリシー", "이용약관": "利用規約", "개인정보처리방침 - Cloud Chatting": "プライバシーポリシー - Cloud Chatting", "이용약관 - Cloud Chatting": "利用規約 - Cloud Chatting"
    });
    Object.assign(dictionaries.es, {
        "클라우드 채팅": "Cloud Chatting", "로그인 - cloudchatting 계정": "Iniciar sesión - cuenta de Cloud Chatting", "관리자 페이지 - Cloud Chatting": "Consola de administración - Cloud Chatting", "관리자 보안 확인 - Cloud Chatting": "Verificación de seguridad de administrador - Cloud Chatting", "개인정보처리방침": "Política de privacidad", "이용약관": "Términos del servicio", "개인정보처리방침 - Cloud Chatting": "Política de privacidad - Cloud Chatting", "이용약관 - Cloud Chatting": "Términos del servicio - Cloud Chatting"
    });

    function t(key) {
        const text = String(key || "").trim();
        // 한국어는 번역 사전이 아니라 화면의 원문 자체가 기준이다.
        // 영어 등 다른 언어를 본 뒤 한국어로 돌아와도 원문으로 정확히 복원한다.
        if (language === "ko") return text;
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
        const originalTitle = document.documentElement.dataset.i18nTitle || document.title;
        if (dictionaries.en[originalTitle]) {
            document.documentElement.dataset.i18nTitle = originalTitle;
            document.title = t(originalTitle);
        }
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
