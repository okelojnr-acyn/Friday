package auth

import (
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
	jwt.RegisteredClaims
}

type Issuer struct {
	secret []byte
	ttl    time.Duration
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
