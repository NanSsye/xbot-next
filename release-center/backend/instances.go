package main

import (
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"time"
)

const onlineWindow = 5 * time.Minute

func instanceRoutes(mux *http.ServeMux, admin func(*http.Request) bool) {
	dir := filepath.Join("data", "instances")
	var mu sync.Mutex
	mux.HandleFunc("POST /api/instances/{id}/revoke", func(w http.ResponseWriter, r *http.Request) {
		if !admin(r) {
			http.Error(w, "请先登录", 401)
			return
		}
		key := r.PathValue("id")
		if !digest.MatchString(key) {
			http.NotFound(w, r)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		err := os.Remove(filepath.Join(dir, key))
		if err != nil && !os.IsNotExist(err) {
			http.Error(w, "撤销失败", 500)
			return
		}
		reply(w, true)
	})
	mux.HandleFunc("POST /api/instances", func(w http.ResponseWriter, r *http.Request) {
		if !admin(r) {
			http.Error(w, "请先登录", 401)
			return
		}
		token := rand.Text()
		sum := sha256.Sum256([]byte(token))
		key := hex.EncodeToString(sum[:])
		if e := os.MkdirAll(dir, 0700); e != nil {
			http.Error(w, "存储不可用", 500)
			return
		}
		f, e := os.OpenFile(filepath.Join(dir, key), os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
		if e != nil {
			http.Error(w, "登记失败", 500)
			return
		}
		f.Close()
		reply(w, map[string]string{"token": token})
	})
	mux.HandleFunc("POST /api/instances/heartbeat", func(w http.ResponseWriter, r *http.Request) {
		token, ok := strings.CutPrefix(r.Header.Get("Authorization"), "Bearer ")
		if !ok || len(token) < 26 || len(token) > 128 {
			http.Error(w, "无效凭据", 401)
			return
		}
		sum := sha256.Sum256([]byte(token))
		path := filepath.Join(dir, hex.EncodeToString(sum[:]))
		mu.Lock()
		defer mu.Unlock()
		info, e := os.Stat(path)
		if os.IsNotExist(e) {
			http.Error(w, "无效凭据", 401)
			return
		}
		if e != nil {
			http.Error(w, "存储不可用", 500)
			return
		}
		if info.Size() == 0 {
			e = os.WriteFile(path, []byte("1"), 0600)
		} else if time.Since(info.ModTime()) >= 30*time.Second {
			now := time.Now()
			e = os.Chtimes(path, now, now)
		}
		if e != nil {
			http.Error(w, "心跳保存失败", 500)
			return
		}
		w.WriteHeader(204)
	})
	mux.HandleFunc("GET /api/instances", func(w http.ResponseWriter, r *http.Request) {
		if !admin(r) {
			http.Error(w, "请先登录", 401)
			return
		}
		entries, e := os.ReadDir(dir)
		if e != nil && !os.IsNotExist(e) {
			http.Error(w, "统计不可用", 500)
			return
		}
		online, registered := 0, 0
		ids := []string{}
		for _, entry := range entries {
			if !digest.MatchString(entry.Name()) || !entry.Type().IsRegular() {
				continue
			}
			info, e := entry.Info()
			if e != nil {
				http.Error(w, "统计不可用", 500)
				return
			}
			registered++
			ids = append(ids, entry.Name())
			if info.Size() > 0 && time.Since(info.ModTime()) <= onlineWindow {
				online++
			}
		}
		reply(w, map[string]any{"online": online, "registered": registered, "ids": ids})
	})
}
