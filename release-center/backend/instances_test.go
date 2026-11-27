package main

import (
	"archive/zip"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestEnrollment(t *testing.T) {
	t.Chdir(t.TempDir())
	mux := http.NewServeMux()
	instanceRoutes(mux, func(r *http.Request) bool { return r.Header.Get("X-Test") == "admin" })
	call := func(method, path, token string, admin bool) *httptest.ResponseRecorder {
		w := httptest.NewRecorder()
		r := httptest.NewRequest(method, path, nil)
		if admin {
			r.Header.Set("X-Test", "admin")
		}
		if token != "" {
			r.Header.Set("Authorization", "Bearer "+token)
		}
		mux.ServeHTTP(w, r)
		return w
	}
	if call("GET", "/api/instances", "", false).Code != 401 {
		t.Fatal("public stats")
	}
	var cred map[string]string
	if err := json.Unmarshal(call("POST", "/api/instances", "", true).Body.Bytes(), &cred); err != nil {
		t.Fatal(err)
	}
	check := func(want int) {
		var stats struct{ Registered, Online int }
		if e := json.Unmarshal(call("GET", "/api/instances", "", true).Body.Bytes(), &stats); e != nil || stats.Registered != 1 || stats.Online != want {
			t.Fatal(stats, e)
		}
	}
	check(0)
	for range 2 {
		if call("POST", "/api/instances/heartbeat", cred["token"], false).Code != 204 {
			t.Fatal("heartbeat")
		}
	}
	check(1)
	files, _ := filepath.Glob("data/instances/*")
	old := time.Now().Add(-6 * time.Minute)
	if e := os.Chtimes(files[0], old, old); e != nil {
		t.Fatal(e)
	}
	check(0)
	path := "/api/instances/" + filepath.Base(files[0]) + "/revoke"
	if call("POST", path, "", false).Code != 401 || call("POST", path, "", true).Code != 200 || call("POST", "/api/instances/heartbeat", cred["token"], false).Code != 401 {
		t.Fatal("invalid revocation lifecycle")
	}
}

func TestArchive(t *testing.T) {
	for _, tt := range []struct {
		names []string
		valid bool
	}{{[]string{"plugin/main.py"}, true}, {[]string{"../main.py"}, false}, {[]string{"a", "a/b"}, false}, {[]string{"a", "A"}, false}} {
		f, e := os.CreateTemp(t.TempDir(), "pkg")
		if e != nil {
			t.Fatal(e)
		}
		z := zip.NewWriter(f)
		for _, n := range tt.names {
			w, e := z.Create(n)
			if e != nil {
				t.Fatal(e)
			}
			w.Write([]byte("test"))
		}
		z.Close()
		f.Close()
		if validArchive(f.Name()) != tt.valid {
			t.Fatal(tt.names)
		}
	}
}
