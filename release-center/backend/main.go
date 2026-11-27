package main

import (
	"archive/zip"
	"crypto/pbkdf2"
	"crypto/rand"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"io/fs"
	"log"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"time"
)

type Item struct {
	Kind, Name, Version, Notes, Digest string
	Size                               int64
}

var mutex sync.Mutex
var sessions = map[string]time.Time{}
var attempts []time.Time
var id = regexp.MustCompile(`^[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}$`)
var digest = regexp.MustCompile(`^[0-9a-f]{64}$`)
var items = []Item{}

// Inspect the uploaded file before it becomes visible in the public catalog.
func validArchive(filename string) bool {
	z, err := zip.OpenReader(filename)
	if err != nil {
		return false
	}
	defer z.Close()
	if len(z.File) == 0 || len(z.File) > 50000 {
		return false
	}
	seen := map[string]bool{}
	var remaining int64 = 512 << 20
	files := 0
	for _, f := range z.File {
		name := strings.TrimSuffix(f.Name, "/")
		dir := f.FileInfo().IsDir()
		if len(name) > 1024 || !fs.ValidPath(name) || name == "." || strings.ContainsAny(name, "\\:\x00") || f.Mode() & ^(fs.ModeDir|fs.ModePerm) != 0 || dir != strings.HasSuffix(f.Name, "/") {
			return false
		}
		key := strings.ToLower(name)
		if _, exists := seen[key]; exists {
			return false
		}
		seen[key] = dir
		if dir {
			if f.UncompressedSize64 != 0 {
				return false
			}
			continue
		}
		if f.UncompressedSize64 > uint64(remaining) {
			return false
		}
		r, err := f.Open()
		if err != nil {
			return false
		}
		n, err := io.Copy(io.Discard, io.LimitReader(r, int64(f.UncompressedSize64)+1))
		r.Close()
		if err != nil || uint64(n) != f.UncompressedSize64 {
			return false
		}
		remaining -= n
		files++
	}
	for key := range seen {
		for i := strings.IndexByte(key, '/'); i >= 0; {
			if dir, ok := seen[key[:i]]; ok && !dir {
				return false
			}
			next := strings.IndexByte(key[i+1:], '/')
			if next < 0 {
				break
			}
			i += next + 1
		}
	}
	return files > 0
}

func reply(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v)
}
func main() {
	salt, e := hex.DecodeString(os.Getenv("ADMIN_SALT"))
	if e != nil || len(salt) < 16 {
		log.Fatal("invalid salt")
	}
	want, e := hex.DecodeString(os.Getenv("ADMIN_HASH"))
	if e != nil || len(want) != 32 {
		log.Fatal("invalid hash")
	}
	user := os.Getenv("ADMIN_USER")
	if user == "" {
		log.Fatal("missing admin")
	}
	if e = os.MkdirAll("data", 0700); e != nil {
		log.Fatal(e)
	}
	raw, e := os.ReadFile("data/catalog.json")
	if e == nil {
		if json.Unmarshal(raw, &items) != nil {
			log.Fatal("invalid catalog")
		}
	} else if !os.IsNotExist(e) {
		log.Fatal(e)
	}
	mux := http.NewServeMux()
	mux.Handle("GET /", http.FileServer(http.Dir("frontend")))
	mux.HandleFunc("GET /api/catalog", func(w http.ResponseWriter, r *http.Request) { mutex.Lock(); defer mutex.Unlock(); reply(w, items) })
	mux.HandleFunc("GET /api/download/{digest}", func(w http.ResponseWriter, r *http.Request) {
		s := r.PathValue("digest")
		if !digest.MatchString(s) {
			http.NotFound(w, r)
			return
		}
		mutex.Lock()
		allowed := false
		for _, i := range items {
			if i.Digest == s {
				allowed = true
				break
			}
		}
		mutex.Unlock()
		if !allowed {
			http.NotFound(w, r)
			return
		}
		w.Header().Set("Content-Disposition", "attachment; filename=\"xbot-package.zip\"")
		w.Header().Set("Content-Type", "application/octet-stream")
		http.ServeFile(w, r, filepath.Join("data", s))
	})
	mux.HandleFunc("POST /api/login", func(w http.ResponseWriter, r *http.Request) {
		r.Body = http.MaxBytesReader(w, r.Body, 4096)
		var input struct{ User, Password string }
		if json.NewDecoder(r.Body).Decode(&input) != nil {
			http.Error(w, "登录参数无效", 400)
			return
		}
		mutex.Lock()
		now := time.Now()
		for len(attempts) > 0 && now.Sub(attempts[0]) > time.Minute {
			attempts = attempts[1:]
		}
		if len(attempts) >= 8 {
			mutex.Unlock()
			http.Error(w, "请稍后再试", 429)
			return
		}
		attempts = append(attempts, now)
		mutex.Unlock()
		got, err := pbkdf2.Key(sha256.New, input.Password, salt, 600000, 32)
		if err != nil || subtle.ConstantTimeCompare(got, want) != 1 || input.User != user {
			http.Error(w, "账号或密码不正确", 401)
			return
		}
		token := rand.Text()
		mutex.Lock()
		for k, v := range sessions {
			if !v.After(now) {
				delete(sessions, k)
			}
		}
		sessions[token] = now.Add(4 * time.Hour)
		mutex.Unlock()
		http.SetCookie(w, &http.Cookie{Name: "__Host-xbotadmin", Value: token, Path: "/", HttpOnly: true, Secure: true, SameSite: http.SameSiteStrictMode, MaxAge: 14400})
		reply(w, true)
	})
	authed := func(r *http.Request) bool {
		c, e := r.Cookie("__Host-xbotadmin")
		if e != nil {
			return false
		}
		mutex.Lock()
		defer mutex.Unlock()
		return sessions[c.Value].After(time.Now())
	}
	mux.HandleFunc("GET /api/session", func(w http.ResponseWriter, r *http.Request) { reply(w, authed(r)) })
	instanceRoutes(mux, authed)
	mux.HandleFunc("POST /api/logout", func(w http.ResponseWriter, r *http.Request) {
		if c, e := r.Cookie("__Host-xbotadmin"); e == nil {
			mutex.Lock()
			delete(sessions, c.Value)
			mutex.Unlock()
		}
		reply(w, true)
	})
	mux.HandleFunc("POST /api/publish", func(w http.ResponseWriter, r *http.Request) {
		if !authed(r) {
			http.Error(w, "请先登录", 401)
			return
		}
		q := r.URL.Query()
		i := Item{Kind: q.Get("kind"), Name: q.Get("name"), Version: q.Get("version"), Notes: q.Get("notes")}
		if (i.Kind != "framework" && i.Kind != "plugin" && i.Kind != "skill") || !id.MatchString(i.Name) || !id.MatchString(i.Version) || len(i.Notes) > 2000 {
			http.Error(w, "发布信息无效", 400)
			return
		}
		f, e := os.CreateTemp("data", ".upload-")
		if e != nil {
			http.Error(w, "存储不可用", 500)
			return
		}
		defer os.Remove(f.Name())
		h := sha256.New()
		i.Size, e = io.Copy(io.MultiWriter(f, h), http.MaxBytesReader(w, r.Body, 128<<20))
		ce := f.Close()
		if e != nil || ce != nil || i.Size == 0 {
			http.Error(w, "上传失败或超出 128 MiB", 400)
			return
		}
		if !validArchive(f.Name()) {
			http.Error(w, "无效发行包：请检查 ZIP 内容、目录和展开大小", 400)
			return
		}
		i.Digest = hex.EncodeToString(h.Sum(nil))
		mutex.Lock()
		defer mutex.Unlock()
		for _, v := range items {
			if v.Kind == i.Kind && v.Name == i.Name && v.Version == i.Version {
				http.Error(w, "版本已存在", 409)
				return
			}
		}
		next := append(append([]Item{}, items...), i)
		buf, e := json.Marshal(next)
		if e == nil {
			e = os.Rename(f.Name(), filepath.Join("data", i.Digest))
		}
		if e == nil {
			e = os.WriteFile("data/.catalog", buf, 0600)
		}
		if e == nil {
			e = os.Rename("data/.catalog", "data/catalog.json")
		}
		if e != nil {
			http.Error(w, "保存失败", 500)
			return
		}
		items = next
		reply(w, i)
	})
	server := http.Server{Addr: "127.0.0.1:3480", ReadHeaderTimeout: 8 * time.Second, ReadTimeout: 4 * time.Minute, WriteTimeout: 5 * time.Minute, IdleTimeout: 45 * time.Second, Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Cache-Control", "no-store")
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'none'")
		machineHeartbeat := r.URL.Path == "/api/instances/heartbeat" && r.Header.Get("Origin") == ""
		if r.Method == "POST" && !machineHeartbeat && r.Header.Get("Origin") != "https://xbot.catmi.si" {
			http.Error(w, "请求来源无效", 403)
			return
		}
		mux.ServeHTTP(w, r)
	})}
	fmt.Println("Xbot release center listening on loopback")
	log.Fatal(server.ListenAndServe())
}
