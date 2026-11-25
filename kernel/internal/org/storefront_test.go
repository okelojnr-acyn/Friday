package org

import "testing"

func TestStorefrontNormalize(t *testing.T) {
	ok := DefaultStorefront()
	ok.Primary, ok.LogoURL = " #ABCDEF ", "https://cdn.example.com/logo.png"
	if msg := ok.normalize(); msg != "" || ok.Primary != "#abcdef" {
		t.Fatalf("valid look refused: %q %q", msg, ok.Primary)
	}
	for name, bad := range map[string]func(*Storefront){
		"colour":  func(s *Storefront) { s.Accent = "red" },
		"font":    func(s *Storefront) { s.BodyFont = "Comic Sans" },
		"corners": func(s *Storefront) { s.Corners = "wavy" },
		"logo":    func(s *Storefront) { s.LogoURL = "javascript:alert(1)" },
		"http":    func(s *Storefront) { s.LogoURL = "http://example.com/a.png" },
		"tagline": func(s *Storefront) { s.Tagline = string(make([]byte, 121)) },
	} {
		s := DefaultStorefront()
		bad(&s)
		if s.normalize() == "" {
			t.Errorf("%s: accepted", name)
		}
	}
}
