package auth

import (
	"context"
	"log"
	"slices"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

// Claims mirrors exactly what packages/py-common/friday_common/auth.py
// expects to find in the token. Changing a field name here means changing
// it there too -- this is the one contract every service in the system
// agrees on.
type Claims struct {
	OrgID string `json:"org_id"`
	Role  string `json:"role"`
	Email string `json:"email"`
	// Via is set on tokens issued to an assistant acting for a user
	// ("guss"). Such tokens only reach app routes (/api/{app}/*), and only
	// the apps in Access: "read" (GET) or "write" (everything). Apps that
	// don't know these fields ignore them; the kernel enforces them.
	Via    string            `json:"via,omitempty"`
	Access map[string]string `json:"access,omitempty"`
	// Who sees what (plan section 12): the person's permissions, their
	// locations ("*" = all) and the people who report to them. Apps
	// enforce access_rules.json with these.
	Perms []string `json:"perms,omitempty"`
	Locs  []string `json:"locs,omitempty"`
	Team  []string `json:"team,omitempty"`
	jwt.RegisteredClaims
}

// ScopeFunc loads a person's perms, locations and team (access.Load).
type ScopeFunc func(ctx context.Context, userID, orgID, role string) (perms, locs, team []string, err error)

type Issuer struct {
	secret []byte
	ttl    time.Duration
	// Scope fills Perms/Locs/Team on every token; nil leaves them empty
	// (tests). Set once at start-up.
	Scope ScopeFunc
}

// fill adds the person's scope to claims. If it can't be loaded the token
// carries no permissions and no locations, so it opens less, never more.
func (iss *Issuer) fill(c *Claims, userID string) {
	// Suppliers aren't members: no permissions, locations or team.
	if iss.Scope == nil || c.Via == SupplierVia {
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	perms, locs, team, err := iss.Scope(ctx, userID, c.OrgID, c.Role)
	if err != nil {
		log.Printf("token scope for %s in %s: %v", userID, c.OrgID, err)
		return
	}
	c.Perms, c.Locs, c.Team = perms, locs, team
}

func NewIssuer(secret string, ttl time.Duration) *Issuer {
	return &Issuer{secret: []byte(secret), ttl: ttl}
}

func (iss *Issuer) Issue(userID, orgID, role, email string) (string, error) {
	now := time.Now()
	claims := Claims{
		OrgID: orgID,
		Role:  role,
		Email: email,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   userID,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(iss.ttl)),
		},
	}
	iss.fill(&claims, userID)
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(iss.secret)
}

// IssueVia issues a short-lived token for userID acting through an
// assistant (`via`), limited to the apps in access. addPerms are jobs the
// token carries on top of the person's own (a till sign-in sells).
func (iss *Issuer) IssueVia(userID, orgID, role, email, via string, access map[string]string, ttl time.Duration, addPerms ...string) (string, error) {
	now := time.Now()
	if access == nil {
		access = map[string]string{}
	}
	claims := Claims{
		OrgID:  orgID,
		Role:   role,
		Email:  email,
		Via:    via,
		Access: access,
		RegisteredClaims: jwt.RegisteredClaims{
			Subject:   userID,
			IssuedAt:  jwt.NewNumericDate(now),
			ExpiresAt: jwt.NewNumericDate(now.Add(ttl)),
		},
	}
	iss.fill(&claims, userID)
	for _, p := range addPerms {
		if !slices.Contains(claims.Perms, p) {
			claims.Perms = append(claims.Perms, p)
		}
	}
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, claims)
	return token.SignedString(iss.secret)
}

func (iss *Issuer) Verify(tokenString string) (*Claims, error) {
	claims := &Claims{}
	_, err := jwt.ParseWithClaims(tokenString, claims, func(t *jwt.Token) (interface{}, error) {
		return iss.secret, nil
	})
	if err != nil {
		return nil, err
	}
	return claims, nil
}
