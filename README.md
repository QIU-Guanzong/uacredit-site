# UACredit

環聯（亞洲）信貸網站、內容管理及貸款申請系統。倉庫包括網站、後台與手機應用程式源碼。

## 網站

需要 Python 3.11 或以上。

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.lock
mkdir -p work/evidence
.venv/bin/python build.py
.venv/bin/python verify_content.py
.venv/bin/python -m unittest test_loans test_cms test_accounts test_account_deletion test_deployment test_loan_backup
```

只預覽網頁可使用 `python3 -m http.server 8743 --directory dist`。網站由 `build.py` 生成；後台是 Flask 應用程式。貸款申請預設關閉；要在隔離的測試環境開啟，網頁建置及後台執行都必須設定 `UACREDIT_APPLICATIONS_ENABLED=1`。這不代表正式網站已啟用申請。

後台啟動時須透過 `UACREDIT_CONFIG` 指向安全保存於倉庫外的設定檔，並透過 `UACREDIT_DATA` 指定資料目錄。客戶資料、憑據、密鑰及備份不可提交到公開倉庫。正式收件前需安排適當存取權限、個人資料告知和可恢復的加密異地備份。

## 手機應用程式

`mobile/` 包含已提交版本的 Capacitor、Android 和 iOS 程式碼。移動端獨立進行中的本地改動沒有包含在此快照中。請在建置前安裝相應平台工具並使用 `mobile/package-lock.json`。

## 倉庫內容

本倉庫是經整理的單次源碼快照，不包括生產資料、憑據、內部部署紀錄或原 Git 歷史。地圖嵌入已從公開快照移除。網站內容、商標及第三方素材的權利屬各自權利人；此倉庫未指定開源授權。
