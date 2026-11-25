package org

import (
	"net/url"
	"regexp"
	"slices"
	"strings"
)

// Storefront is the online store's look (core.orgs.storefront), set on
// Store settings and handed to the store kit as its brand tokens.
type Storefront struct {
	StoreName   string `json:"store_name"`
	Tagline     string `json:"tagline"`
	LogoURL     string `json:"logo_url"`
	Primary     string `json:"primary_color"`
	Accent      string `json:"accent_color"`
	Background  string `json:"background_color"`
	Text        string `json:"text_color"`
	HeadingFont string `json:"heading_font"`
	BodyFont    string `json:"body_font"`
	// Corners: square, soft or round.
	Corners string `json:"corners"`
}

// StoreFonts are Google Fonts the store kit can load; a short list keeps
// every pairing readable and the kit's font loading fixed.
var StoreFonts = []string{
	"Inter", "DM Sans", "Manrope", "Plus Jakarta Sans", "Work Sans", "Nunito", "Poppins", "Outfit",
	"Fraunces", "Playfair Display", "Lora", "DM Serif Display", "Space Grotesk", "Sora", "Lexend",
}

var hexColorRe = regexp.MustCompile(`^#[0-9a-fA-F]{6}$`)

// DefaultStorefront: a neutral, readable start.
func DefaultStorefront() Storefront {
	return Storefront{
		Primary: "#1f2937", Accent: "#f59e0b", Background: "#ffffff", Text: "#111827",
		HeadingFont: "DM Sans", BodyFont: "Inter", Corners: "soft",
	}
}

// normalize trims and checks the look; the message suits an owner.
func (s *Storefront) normalize() string {
	s.StoreName = strings.TrimSpace(s.StoreName)
	s.Tagline = strings.TrimSpace(s.Tagline)
	s.LogoURL = strings.TrimSpace(s.LogoURL)
	if len(s.StoreName) > 60 || len(s.Tagline) > 120 {
		return "the store name is up to 60 characters and the tagline up to 120"
	}
	if s.LogoURL != "" {
		u, err := url.Parse(s.LogoURL)
		if err != nil || u.Scheme != "https" || u.Host == "" || len(s.LogoURL) > 500 {
			return "the logo is an https:// link to an image"
		}
	}
	for _, c := range []*string{&s.Primary, &s.Accent, &s.Background, &s.Text} {
		*c = strings.ToLower(strings.TrimSpace(*c))
		if !hexColorRe.MatchString(*c) {
			return "colours are hex codes like #1f2937"
		}
	}
	if !slices.Contains(StoreFonts, s.HeadingFont) || !slices.Contains(StoreFonts, s.BodyFont) {
		return "choose fonts from the list"
	}
	if !slices.Contains([]string{"square", "soft", "round"}, s.Corners) {
		return "corners are square, soft or round"
	}
	return ""
}
